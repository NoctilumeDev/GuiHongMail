package infrastructure

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
	smtp "github.com/emersion/go-smtp"
	"github.com/google/uuid"
)

const ingressEventTopic = "guihong.ingress.accepted.v1"

type acceptedRecipient struct {
	AccountID string `json:"accountId"`
	Address   string `json:"address"`
}

type acceptedEvent struct {
	Version       int                 `json:"version"`
	SourceService string              `json:"sourceService"`
	SpoolID       string              `json:"spoolId"`
	RawSHA256     string              `json:"rawSha256"`
	RawSize       int64               `json:"rawSize"`
	RawURL        string              `json:"rawUrl"`
	AckURL        string              `json:"ackUrl"`
	Recipients    []acceptedRecipient `json:"recipients"`
}

type durableBackend struct {
	runtime *platform.Runtime
	slots   chan struct{}
}

func (backend *durableBackend) NewSession(*smtp.Conn) (smtp.Session, error) {
	select {
	case backend.slots <- struct{}{}:
		return &durableSession{runtime: backend.runtime, release: func() { <-backend.slots }}, nil
	default:
		return nil, &smtp.SMTPError{Code: 421, EnhancedCode: smtp.EnhancedCode{4, 5, 3}, Message: "Concurrent session limit reached"}
	}
}

type durableSession struct {
	runtime    *platform.Runtime
	mailFrom   string
	recipients []acceptedRecipient
	release    func()
	releaseOne sync.Once
}

func (session *durableSession) Reset() { session.mailFrom = ""; session.recipients = nil }
func (session *durableSession) Logout() error {
	session.releaseOne.Do(session.release)
	return nil
}
func (session *durableSession) Mail(from string, _ *smtp.MailOptions) error {
	if !session.runtime.Writable(context.Background()) {
		return &smtp.SMTPError{Code: 451, EnhancedCode: smtp.EnhancedCode{4, 3, 0}, Message: "Service temporarily unavailable"}
	}
	if len(from) > 254 || strings.ContainsAny(from, "\r\n<>") {
		return &smtp.SMTPError{Code: 553, EnhancedCode: smtp.EnhancedCode{5, 1, 7}, Message: "Invalid reverse path"}
	}
	session.mailFrom = strings.ToLower(from)
	session.recipients = nil
	return nil
}
func (session *durableSession) Rcpt(to string, _ *smtp.RcptOptions) error {
	to = strings.ToLower(strings.TrimSpace(to))
	if len(session.recipients) >= 10 {
		return &smtp.SMTPError{Code: 452, EnhancedCode: smtp.EnhancedCode{4, 5, 3}, Message: "Recipient limit exceeded"}
	}
	at := strings.LastIndex(to, "@")
	if at < 1 || !strings.EqualFold(to[at+1:], "guihong.test") {
		return &smtp.SMTPError{Code: 550, EnhancedCode: smtp.EnhancedCode{5, 7, 1}, Message: "Relay denied"}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	target := "http://127.0.0.1:18080/internal/admission?address=" + url.QueryEscape(to)
	status, data, err := platform.InternalRequest(ctx, session.runtime, http.MethodGet, target, nil, 4096)
	if err != nil || status == http.StatusServiceUnavailable {
		return &smtp.SMTPError{Code: 451, EnhancedCode: smtp.EnhancedCode{4, 3, 0}, Message: "Recipient directory unavailable"}
	}
	if status != http.StatusOK {
		return &smtp.SMTPError{Code: 550, EnhancedCode: smtp.EnhancedCode{5, 1, 1}, Message: "Unknown local recipient"}
	}
	var admitted struct {
		AccountID string `json:"accountId"`
	}
	if json.Unmarshal(data, &admitted) != nil || admitted.AccountID == "" {
		return &smtp.SMTPError{Code: 451, EnhancedCode: smtp.EnhancedCode{4, 3, 0}, Message: "Recipient directory invalid"}
	}
	for _, existing := range session.recipients {
		if existing.AccountID == admitted.AccountID {
			return nil
		}
	}
	session.recipients = append(session.recipients, acceptedRecipient{AccountID: admitted.AccountID, Address: to})
	return nil
}
func (session *durableSession) Data(reader io.Reader) error {
	if len(session.recipients) == 0 || !session.runtime.Writable(context.Background()) {
		return &smtp.SMTPError{Code: 451, EnhancedCode: smtp.EnhancedCode{4, 3, 0}, Message: "Durable responsibility unavailable"}
	}
	raw, err := io.ReadAll(io.LimitReader(reader, 5*1024*1024+1))
	if err != nil || len(raw) == 0 || len(raw) > 5*1024*1024 {
		return &smtp.SMTPError{Code: 552, EnhancedCode: smtp.EnhancedCode{5, 3, 4}, Message: "Message size exceeded"}
	}
	if _, err := persistSpool(context.Background(), session.runtime, session.mailFrom, session.recipients, raw); err != nil {
		return &smtp.SMTPError{Code: 451, EnhancedCode: smtp.EnhancedCode{4, 3, 0}, Message: "Message not durably accepted"}
	}
	return nil
}

func persistSpool(ctx context.Context, runtime *platform.Runtime, from string, recipients []acceptedRecipient, raw []byte) (string, error) {
	sorted := append([]acceptedRecipient(nil), recipients...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].AccountID < sorted[j].AccountID })
	binding, _ := json.Marshal(struct {
		From string              `json:"from"`
		To   []acceptedRecipient `json:"to"`
		Raw  string              `json:"raw"`
	}{from, sorted, platform.SHA256(raw)})
	receipt := platform.SHA256(binding)
	var existing string
	if err := runtime.Database.QueryRowContext(ctx, "SELECT spool_id FROM accepted_spools WHERE source_receipt=?", receipt).Scan(&existing); err == nil {
		return existing, nil
	} else if !errors.Is(err, sql.ErrNoRows) {
		return "", err
	}
	spoolID := uuid.NewString()
	blob, err := runtime.Objects.Stage(ctx, uuid.NewString(), "ingress-spool:"+spoolID, raw)
	if err != nil {
		return "", err
	}
	if blob, err = runtime.Objects.Reference(ctx, blob.ID, "INGRESS_SPOOL", spoolID); err != nil {
		return "", err
	}
	event := acceptedEvent{Version: 1, SourceService: "ingress", SpoolID: spoolID, RawSHA256: blob.SHA256, RawSize: blob.Size,
		RawURL: "http://127.0.0.1:18081/internal/spools/" + spoolID + "/raw",
		AckURL: "http://127.0.0.1:18081/internal/spools/" + spoolID + "/ack", Recipients: recipients}
	payload, _ := json.Marshal(event)
	err = runtime.Witness.Write(ctx, "ingress-accept|"+spoolID+"|"+blob.SHA256, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, `INSERT INTO accepted_spools(spool_id,source_receipt,mail_from,raw_object_id,raw_sha256,raw_size) VALUES(?,?,?,?,?,?)`, spoolID, receipt, from, blob.ID, blob.SHA256, blob.Size); err != nil {
			return err
		}
		for ordinal, recipient := range recipients {
			if _, err := tx.ExecContext(ctx, `INSERT INTO accepted_recipients(spool_id,ordinal_no,account_id,address) VALUES(?,?,?,?)`, spoolID, ordinal, recipient.AccountID, recipient.Address); err != nil {
				return err
			}
		}
		_, err := tx.ExecContext(ctx, `INSERT INTO ingress_outbox(event_id,aggregate_id,topic,message_key,payload) VALUES(?,?, 'guihong.ingress.accepted.v1',?,?)`, uuid.NewString(), spoolID, "ingress:"+spoolID, string(payload))
		return err
	})
	if err != nil {
		var unknown *platform.CommitUnknownError
		if !errors.As(err, &unknown) {
			_ = runtime.Objects.Dereference(ctx, blob.ID, "INGRESS_SPOOL", spoolID)
		}
		return "", err
	}
	return spoolID, nil
}

func RunDurableSMTP(ctx context.Context, runtime *platform.Runtime) error {
	ensureCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	err := platform.EnsureTopic(ensureCtx, runtime, ingressEventTopic)
	cancel()
	if err != nil {
		return err
	}
	listener, err := net.Listen("tcp", runtime.Config.SMTPAddress)
	if err != nil {
		return err
	}
	server := smtp.NewServer(&durableBackend{runtime: runtime, slots: make(chan struct{}, 2)})
	server.Domain = "guihong.test"
	server.MaxRecipients = 10
	server.MaxMessageBytes = 5 * 1024 * 1024
	server.ReadTimeout = 10 * time.Second
	server.WriteTimeout = 10 * time.Second
	errorsChannel := make(chan error, 2)
	go func() { errorsChannel <- server.Serve(listener) }()
	go func() { errorsChannel <- publishIngress(ctx, runtime) }()
	select {
	case <-ctx.Done():
		_ = server.Close()
		return nil
	case err := <-errorsChannel:
		_ = server.Close()
		return err
	}
}

func publishIngress(ctx context.Context, runtime *platform.Runtime) error {
	publisher, err := platform.NewPublisher(runtime, "guihong-ingress-outbox-v1")
	if err != nil {
		return err
	}
	defer publisher.Close()
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		if runtime.Writable(ctx) {
			rows, err := runtime.Database.QueryContext(ctx, `SELECT event_id,topic,message_key,payload FROM ingress_outbox WHERE published_at IS NULL AND next_attempt_at<=CURRENT_TIMESTAMP(6) ORDER BY created_at,event_id LIMIT 20`)
			if err != nil {
				return err
			}
			type pending struct {
				id, topic, key string
				payload        []byte
			}
			items := []pending{}
			for rows.Next() {
				var value pending
				if err := rows.Scan(&value.id, &value.topic, &value.key, &value.payload); err != nil {
					rows.Close()
					return err
				}
				items = append(items, value)
			}
			rows.Close()
			for _, item := range items {
				messageID, failure := publisher.Send(ctx, item.topic, item.key, item.payload)
				if failure != nil {
					break
				}
				if failure = runtime.Witness.Write(ctx, "ingress-outbox-published|"+item.id+"|"+messageID, func(tx *sql.Tx) error {
					_, err := tx.ExecContext(ctx, "UPDATE ingress_outbox SET published_at=CURRENT_TIMESTAMP(6),attempts=attempts+1 WHERE event_id=? AND published_at IS NULL", item.id)
					return err
				}); failure != nil {
					break
				}
			}
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func RegisterIngress(mux *http.ServeMux, runtime *platform.Runtime) {
	mux.Handle("GET /internal/spools/{id}/raw", internalHandler(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var object, digest string
		var size int64
		err := runtime.Database.QueryRowContext(request.Context(), "SELECT raw_object_id,raw_sha256,raw_size FROM accepted_spools WHERE spool_id=?", request.PathValue("id")).Scan(&object, &digest, &size)
		if errors.Is(err, sql.ErrNoRows) {
			http.Error(writer, "not found", http.StatusNotFound)
			return
		}
		if err != nil {
			http.Error(writer, "unavailable", http.StatusServiceUnavailable)
			return
		}
		data, err := runtime.Objects.Read(request.Context(), object)
		if err != nil || int64(len(data)) != size || platform.SHA256(data) != digest {
			http.Error(writer, "unavailable", http.StatusServiceUnavailable)
			return
		}
		writer.Header().Set("Content-Type", "application/octet-stream")
		writer.WriteHeader(http.StatusOK)
		_, _ = writer.Write(data)
	})))
	mux.Handle("POST /internal/spools/{id}/ack", internalHandler(runtime, http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var input struct {
			RawSHA256 string `json:"rawSha256"`
			Imported  bool   `json:"imported"`
		}
		if err := json.NewDecoder(io.LimitReader(request.Body, 4096)).Decode(&input); err != nil || !input.Imported {
			http.Error(writer, "invalid", http.StatusBadRequest)
			return
		}
		err := runtime.Witness.Write(request.Context(), "ingress-ack|"+request.PathValue("id")+"|"+input.RawSHA256, func(tx *sql.Tx) error {
			result, err := tx.ExecContext(request.Context(), "UPDATE accepted_spools SET state='GC_ELIGIBLE',acked_at=COALESCE(acked_at,CURRENT_TIMESTAMP(6)) WHERE spool_id=? AND raw_sha256=? AND state IN('ACCEPTED','ACKED','GC_ELIGIBLE')", request.PathValue("id"), input.RawSHA256)
			if err != nil {
				return err
			}
			rows, _ := result.RowsAffected()
			if rows != 1 {
				return fmt.Errorf("spool ack mismatch")
			}
			return nil
		})
		if err != nil {
			http.Error(writer, "unavailable", http.StatusServiceUnavailable)
			return
		}
		writer.WriteHeader(http.StatusNoContent)
	})))
}

func internalHandler(runtime *platform.Runtime, next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if err := runtime.RequireInternal(request.Header.Get("X-GuiHong-Service"), request.Header.Get("Authorization")); err != nil {
			http.Error(writer, "unauthorized", http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(writer, request)
	})
}
