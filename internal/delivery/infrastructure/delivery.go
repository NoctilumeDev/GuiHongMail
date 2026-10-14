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
	"net/mail"
	"net/textproto"
	"regexp"
	"strings"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
	"github.com/google/uuid"
)

const sendTopic = "guihong_mail_send_v1"

var (
	errNoJob       = errors.New("no delivery job")
	errSendStarted = errors.New("send already started")
	errBadDecision = errors.New("invalid delivery decision")
	retryKey       = regexp.MustCompile(`^[\x21-\x7e]{1,128}$`)
)

type sendEvent struct {
	Version         int    `json:"version"`
	SourceService   string `json:"sourceService"`
	IntentID        string `json:"intentId"`
	DispatchScopeID string `json:"dispatchScopeId"`
	Sender          string `json:"sender"`
	Envelope        []struct {
		Kind    string `json:"kind"`
		Address string `json:"address"`
	} `json:"envelope"`
	RawSHA256 string `json:"rawSha256"`
	RawSize   int64  `json:"rawSize"`
	RawURL    string `json:"rawUrl"`
}

type claim struct {
	JobID, ScopeID, IntentID, Sender, Recipient, RawSHA256, AttemptID string
	RawSize, Epoch                                                    int64
	AttemptCount                                                      int
	DuplicateRisk                                                     bool
	PriorAttempt                                                      sql.NullString
}

type protocolResult struct {
	Code          int
	LastStage     string
	DataSubmitted bool
	Outcome       string
	Evidence      string
}

func Run(ctx context.Context, runtime *platform.Runtime) error {
	ensure, cancel := context.WithTimeout(ctx, 10*time.Second)
	err := platform.EnsureTopic(ensure, runtime, sendTopic)
	cancel()
	if err != nil {
		return err
	}
	errorsChannel := make(chan error, 2)
	go func() {
		errorsChannel <- platform.Consume(ctx, runtime, "guihong_delivery_v1", sendTopic, func(callback context.Context, _ string, body []byte) error {
			return acceptEvent(callback, runtime, body)
		})
	}()
	go func() { errorsChannel <- workerLoop(ctx, runtime) }()
	select {
	case <-ctx.Done():
		return nil
	case failure := <-errorsChannel:
		return failure
	}
}

func acceptEvent(ctx context.Context, runtime *platform.Runtime, body []byte) error {
	var event sendEvent
	if err := json.Unmarshal(body, &event); err != nil || event.Version != 1 || event.SourceService != "mailbox" ||
		!validUUID(event.IntentID) || !validUUID(event.DispatchScopeID) || len(event.RawSHA256) != 64 ||
		event.RawSize < 1 || event.RawSize > 5*1024*1024 || len(event.Envelope) < 1 || len(event.Envelope) > 10 {
		return fmt.Errorf("invalid send event")
	}
	if address, err := mail.ParseAddress(event.Sender); err != nil || !strings.EqualFold(address.Address, event.Sender) {
		return fmt.Errorf("invalid sender")
	}
	recipients := make([]string, 0, len(event.Envelope))
	seen := map[string]bool{}
	for _, value := range event.Envelope {
		address, err := mail.ParseAddress(value.Address)
		if err != nil {
			return fmt.Errorf("invalid recipient")
		}
		normalized := strings.ToLower(address.Address)
		if !seen[normalized] {
			seen[normalized] = true
			recipients = append(recipients, normalized)
		}
	}
	digest := platform.SHA256(body)
	return runtime.Witness.Write(ctx, "delivery-event|"+event.IntentID+"|"+digest, func(tx *sql.Tx) error {
		var existing string
		err := tx.QueryRowContext(ctx, "SELECT payload_sha256 FROM delivery_events WHERE source_service='mailbox' AND source_intent_id=? FOR UPDATE", event.IntentID).Scan(&existing)
		if err == nil {
			if existing != digest {
				return fmt.Errorf("delivery event payload conflict")
			}
			return nil
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		var state, rawDigest, sender string
		var rawSize int64
		err = tx.QueryRowContext(ctx, "SELECT state,raw_sha256,raw_size,sender_address FROM dispatch_scopes WHERE scope_id=? FOR UPDATE", event.DispatchScopeID).Scan(&state, &rawDigest, &rawSize, &sender)
		switch {
		case errors.Is(err, sql.ErrNoRows):
			if _, err = tx.ExecContext(ctx, `INSERT INTO dispatch_scopes(scope_id,source_intent_id,source_service,raw_sha256,raw_size,sender_address) VALUES(?,?,'mailbox',?,?,?)`, event.DispatchScopeID, event.IntentID, event.RawSHA256, event.RawSize, event.Sender); err != nil {
				return err
			}
			for _, recipient := range recipients {
				if _, err = tx.ExecContext(ctx, "INSERT INTO delivery_jobs(job_id,scope_id,recipient) VALUES(?,?,?)", uuid.NewString(), event.DispatchScopeID, recipient); err != nil {
					return err
				}
			}
		case err != nil:
			return err
		case rawDigest != event.RawSHA256 || rawSize != event.RawSize || !strings.EqualFold(sender, event.Sender):
			return fmt.Errorf("cancel tombstone does not match event")
		case state != "CANCELLED":
			return fmt.Errorf("scope identity conflict")
		}
		_, err = tx.ExecContext(ctx, "INSERT INTO delivery_events(source_service,source_intent_id,payload_sha256) VALUES('mailbox',?,?)", event.IntentID, digest)
		return err
	})
}

func workerLoop(ctx context.Context, runtime *platform.Runtime) error {
	worker := uuid.NewString()
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()
	for {
		if runtime.Writable(ctx) {
			if err := recoverExpired(ctx, runtime); err != nil {
				return err
			}
			job, err := claimJob(ctx, runtime, worker)
			if err != nil && !errors.Is(err, errNoJob) {
				return err
			}
			if err == nil {
				result := deliver(ctx, runtime, job)
				if err := finish(ctx, runtime, job, result); err != nil {
					return err
				}
				continue
			}
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}

func claimJob(ctx context.Context, runtime *platform.Runtime, worker string) (claim, error) {
	var candidate, scope string
	err := runtime.Database.QueryRowContext(ctx, `SELECT j.job_id,j.scope_id FROM delivery_jobs j JOIN dispatch_scopes s ON s.scope_id=j.scope_id WHERE j.state IN('QUEUED','RETRY_WAIT') AND j.next_attempt_at<=CURRENT_TIMESTAMP(6) AND s.state IN('QUEUED','STARTED') ORDER BY j.next_attempt_at,j.job_id LIMIT 1`).Scan(&candidate, &scope)
	if errors.Is(err, sql.ErrNoRows) {
		return claim{}, errNoJob
	}
	if err != nil {
		return claim{}, err
	}
	var result claim
	claimed := false
	err = runtime.Witness.Write(ctx, "delivery-claim|"+candidate+"|"+worker, func(tx *sql.Tx) error {
		var scopeState string
		if err := tx.QueryRowContext(ctx, "SELECT state FROM dispatch_scopes WHERE scope_id=? FOR UPDATE", scope).Scan(&scopeState); err != nil {
			return err
		}
		if scopeState != "QUEUED" && scopeState != "STARTED" {
			return nil
		}
		var state string
		if err := tx.QueryRowContext(ctx, `SELECT j.job_id,j.scope_id,s.source_intent_id,s.sender_address,j.recipient,s.raw_sha256,s.raw_size,j.attempt_count,j.active_epoch,j.state FROM delivery_jobs j JOIN dispatch_scopes s ON s.scope_id=j.scope_id WHERE j.job_id=? FOR UPDATE`, candidate).Scan(
			&result.JobID, &result.ScopeID, &result.IntentID, &result.Sender, &result.Recipient, &result.RawSHA256, &result.RawSize, &result.AttemptCount, &result.Epoch, &state); err != nil {
			return err
		}
		if (state != "QUEUED" && state != "RETRY_WAIT") || result.ScopeID != scope {
			return nil
		}
		result.AttemptCount++
		result.Epoch++
		result.AttemptID = uuid.NewString()
		var prior string
		if err := tx.QueryRowContext(ctx, "SELECT attempt_id FROM delivery_attempts WHERE job_id=? AND outcome='UNKNOWN' ORDER BY epoch_no DESC LIMIT 1", result.JobID).Scan(&prior); err == nil {
			result.DuplicateRisk = true
			result.PriorAttempt = sql.NullString{String: prior, Valid: true}
		} else if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE dispatch_scopes SET state='STARTED',ever_started=1,version_no=version_no+1 WHERE scope_id=?`, result.ScopeID); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE delivery_jobs SET state='STARTED',attempt_count=?,active_epoch=?,worker_id=?,lease_until=DATE_ADD(CURRENT_TIMESTAMP(6),INTERVAL 30 SECOND) WHERE job_id=?`, result.AttemptCount, result.Epoch, worker, result.JobID); err != nil {
			return err
		}
		_, err := tx.ExecContext(ctx, `INSERT INTO delivery_attempts(attempt_id,job_id,epoch_no,worker_id,last_stage,duplicate_risk_ack,prior_attempt_id) VALUES(?,?,?,?,'CLAIMED',?,?)`, result.AttemptID, result.JobID, result.Epoch, worker, result.DuplicateRisk, result.PriorAttempt)
		claimed = err == nil
		return err
	})
	if err != nil {
		return claim{}, err
	}
	if !claimed {
		return claim{}, errNoJob
	}
	return result, nil
}

func recordStage(ctx context.Context, runtime *platform.Runtime, job claim, stage string, submitted bool) error {
	return runtime.Witness.Write(ctx, "delivery-stage|"+job.AttemptID+"|"+stage, func(tx *sql.Tx) error {
		result, err := tx.ExecContext(ctx, `UPDATE delivery_attempts SET last_stage=?,data_submitted=? WHERE attempt_id=? AND completed_at IS NULL`, stage, submitted, job.AttemptID)
		if err != nil {
			return err
		}
		rows, _ := result.RowsAffected()
		if rows != 1 {
			return fmt.Errorf("attempt is not active")
		}
		_, err = tx.ExecContext(ctx, `UPDATE delivery_jobs SET lease_until=DATE_ADD(CURRENT_TIMESTAMP(6),INTERVAL 30 SECOND) WHERE job_id=? AND state='STARTED'`, job.JobID)
		return err
	})
}

func deliver(ctx context.Context, runtime *platform.Runtime, job claim) protocolResult {
	transcript := []string{"attempt=" + job.AttemptID, "recipient=" + job.Recipient}
	result := protocolResult{LastStage: "CONNECT"}
	status, raw, err := platform.InternalRequest(ctx, runtime, http.MethodGet, "http://127.0.0.1:18080/internal/send-intents/"+job.IntentID+"/raw", nil, 5*1024*1024)
	if err != nil || status != http.StatusOK || int64(len(raw)) != job.RawSize || platform.SHA256(raw) != job.RawSHA256 {
		transcript = append(transcript, "raw=unavailable")
		result.Outcome, result.Evidence = "TEMPORARY_FAILURE", platform.SHA256([]byte(strings.Join(transcript, "\n")))
		return result
	}
	dialer := net.Dialer{Timeout: 10 * time.Second}
	connection, err := dialer.DialContext(ctx, "tcp", runtime.Config.SMTPAddress)
	if err != nil {
		transcript = append(transcript, "connect="+err.Error())
		result.Outcome, result.Evidence = "TEMPORARY_FAILURE", platform.SHA256([]byte(strings.Join(transcript, "\n")))
		return result
	}
	defer connection.Close()
	_ = connection.SetDeadline(time.Now().Add(10 * time.Second))
	protocol := textproto.NewConn(connection)
	defer protocol.Close()
	read := func(stage string, expected int) bool {
		code, message, failure := protocol.ReadResponse(expected)
		result.Code, result.LastStage = code, stage
		transcript = append(transcript, fmt.Sprintf("%s=%d %s", stage, code, message))
		if failure != nil {
			if protocolError := new(textproto.Error); errors.As(failure, &protocolError) {
				result.Code = protocolError.Code
			}
			transcript = append(transcript, "error="+failure.Error())
			return false
		}
		return true
	}
	command := func(stage string, expected int, format string, values ...any) bool {
		id, failure := protocol.Cmd(format, values...)
		if failure != nil {
			result.LastStage = stage
			transcript = append(transcript, "error="+failure.Error())
			return false
		}
		protocol.StartResponse(id)
		defer protocol.EndResponse(id)
		return read(stage, expected)
	}
	if !read("GREETING", 220) || !command("EHLO", 250, "EHLO guihong.local") || !command("MAIL", 250, "MAIL FROM:<%s>", job.Sender) || !command("RCPT", 250, "RCPT TO:<%s>", job.Recipient) || !command("DATA_READY", 354, "DATA") {
		result.Outcome = smtpFailureOutcome(result.Code, false)
		result.Evidence = platform.SHA256([]byte(strings.Join(transcript, "\n")))
		return result
	}
	if err := recordStage(ctx, runtime, job, "DATA_WRITING", false); err != nil {
		result.Outcome, result.Evidence = "TEMPORARY_FAILURE", platform.SHA256([]byte(err.Error()))
		return result
	}
	writer := protocol.DotWriter()
	if _, err = writer.Write(raw); err != nil {
		result.LastStage = "DATA_WRITE"
		transcript = append(transcript, "error="+err.Error())
		result.Outcome, result.Evidence = "TEMPORARY_FAILURE", platform.SHA256([]byte(strings.Join(transcript, "\n")))
		return result
	}
	// From this durable marker onward a crash or missing final reply is treated
	// conservatively: the next hop may have accepted the message.
	if err := recordStage(ctx, runtime, job, "DATA_FINALIZING", true); err != nil {
		result.Outcome, result.DataSubmitted, result.Evidence = "UNKNOWN", true, platform.SHA256([]byte(err.Error()))
		return result
	}
	result.DataSubmitted = true
	if err = writer.Close(); err != nil {
		result.LastStage = "DATA_TERMINATOR"
		transcript = append(transcript, "error="+err.Error())
		result.Outcome, result.Evidence = "UNKNOWN", platform.SHA256([]byte(strings.Join(transcript, "\n")))
		return result
	}
	if err := recordStage(ctx, runtime, job, "DATA_SUBMITTED", true); err != nil {
		result.Outcome, result.Evidence = "UNKNOWN", platform.SHA256([]byte(err.Error()))
		return result
	}
	if !read("FINAL_REPLY", 250) {
		result.Outcome = smtpFailureOutcome(result.Code, true)
		result.Evidence = platform.SHA256([]byte(strings.Join(transcript, "\n")))
		return result
	}
	result.Outcome, result.Evidence = "NEXT_HOP_ACCEPTED", platform.SHA256([]byte(strings.Join(transcript, "\n")))
	return result
}

func smtpFailureOutcome(code int, dataSubmitted bool) string {
	if code >= 500 && code <= 599 {
		return "PERMANENT_FAILURE"
	}
	if code >= 400 && code <= 499 {
		return "TEMPORARY_FAILURE"
	}
	if dataSubmitted {
		return "UNKNOWN"
	}
	return "TEMPORARY_FAILURE"
}

func finish(ctx context.Context, runtime *platform.Runtime, job claim, result protocolResult) error {
	state := result.Outcome
	nextDelay := 0
	if result.Outcome == "TEMPORARY_FAILURE" {
		if job.AttemptCount < 3 {
			state = "RETRY_WAIT"
			nextDelay = job.AttemptCount
			if nextDelay > 2 {
				nextDelay = 2
			}
		} else {
			state = "PERMANENT_FAILURE"
		}
	}
	return runtime.Witness.Write(ctx, "delivery-finish|"+job.AttemptID+"|"+state+"|"+result.Evidence, func(tx *sql.Tx) error {
		var code any
		if result.Code != 0 {
			code = result.Code
		}
		if _, err := tx.ExecContext(ctx, `UPDATE delivery_attempts SET completed_at=CURRENT_TIMESTAMP(6),last_stage=?,data_submitted=?,smtp_code=?,outcome=?,evidence_sha256=? WHERE attempt_id=? AND completed_at IS NULL`, result.LastStage, result.DataSubmitted, code, result.Outcome, result.Evidence, job.AttemptID); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE delivery_jobs SET state=?,next_attempt_at=DATE_ADD(CURRENT_TIMESTAMP(6),INTERVAL ? SECOND),worker_id=NULL,lease_until=NULL WHERE job_id=? AND state='STARTED'`, state, nextDelay, job.JobID); err != nil {
			return err
		}
		return reconcileScope(ctx, tx, job.ScopeID)
	})
}

func recoverExpired(ctx context.Context, runtime *platform.Runtime) error {
	var jobID string
	err := runtime.Database.QueryRowContext(ctx, `SELECT job_id FROM delivery_jobs WHERE state='STARTED' AND lease_until<CURRENT_TIMESTAMP(6) ORDER BY lease_until LIMIT 1`).Scan(&jobID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	return runtime.Witness.Write(ctx, "delivery-recover|"+jobID, func(tx *sql.Tx) error {
		var scope, state, attempt string
		var count int
		var submitted bool
		if err := tx.QueryRowContext(ctx, `SELECT j.scope_id,j.state,j.attempt_count,a.attempt_id,a.data_submitted FROM delivery_jobs j JOIN delivery_attempts a ON a.job_id=j.job_id AND a.epoch_no=j.active_epoch WHERE j.job_id=? FOR UPDATE`, jobID).Scan(&scope, &state, &count, &attempt, &submitted); err != nil {
			return err
		}
		if state != "STARTED" {
			return nil
		}
		outcome, next, delay := "UNKNOWN", "UNKNOWN", 0
		if !submitted && count < 3 {
			outcome, next, delay = "TEMPORARY_FAILURE", "RETRY_WAIT", count
		} else if !submitted {
			outcome, next = "TEMPORARY_FAILURE", "PERMANENT_FAILURE"
		}
		evidence := platform.SHA256([]byte("expired-lease|" + attempt + "|" + outcome))
		if _, err := tx.ExecContext(ctx, `UPDATE delivery_attempts SET completed_at=CURRENT_TIMESTAMP(6),outcome=?,evidence_sha256=? WHERE attempt_id=? AND completed_at IS NULL`, outcome, evidence, attempt); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE delivery_jobs SET state=?,next_attempt_at=DATE_ADD(CURRENT_TIMESTAMP(6),INTERVAL ? SECOND),worker_id=NULL,lease_until=NULL WHERE job_id=?`, next, delay, jobID); err != nil {
			return err
		}
		return reconcileScope(ctx, tx, scope)
	})
}

func reconcileScope(ctx context.Context, tx *sql.Tx, scope string) error {
	var active int
	if err := tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM delivery_jobs WHERE scope_id=? AND state IN('QUEUED','STARTED','RETRY_WAIT')`, scope).Scan(&active); err != nil {
		return err
	}
	state := "COMPLETED"
	if active > 0 {
		state = "QUEUED"
	}
	_, err := tx.ExecContext(ctx, "UPDATE dispatch_scopes SET state=?,version_no=version_no+1 WHERE scope_id=? AND state<>'CANCELLED'", state, scope)
	return err
}

func Register(mux *http.ServeMux, runtime *platform.Runtime) {
	mux.Handle("GET /internal/dispatch-scopes/{scope}", internal(runtime, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		value, err := scopeStatus(r.Context(), runtime.Database, r.PathValue("scope"))
		if errors.Is(err, sql.ErrNoRows) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if err != nil {
			http.Error(w, "unavailable", http.StatusServiceUnavailable)
			return
		}
		writeJSON(w, http.StatusOK, value)
	})))
	mux.Handle("POST /internal/dispatch-scopes/{scope}/cancel", internal(runtime, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		input, err := decodeDecision(r)
		if err == nil {
			err = cancelScope(r.Context(), runtime, r.PathValue("scope"), input)
		}
		if errors.Is(err, errSendStarted) {
			writeJSON(w, http.StatusConflict, map[string]string{"code": "SEND_ALREADY_STARTED"})
			return
		}
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"code": "INVALID_CANCEL_REQUEST"})
			return
		}
		value, _ := scopeStatus(r.Context(), runtime.Database, r.PathValue("scope"))
		writeJSON(w, http.StatusOK, value)
	})))
	mux.Handle("POST /internal/dispatch-scopes/{scope}/retry-unknown", internal(runtime, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		input, err := decodeDecision(r)
		if err == nil && (!input.ConfirmDuplicateRisk || !retryKey.MatchString(input.RequestKey)) {
			err = errBadDecision
		}
		if err == nil {
			err = retryUnknown(r.Context(), runtime, r.PathValue("scope"), input)
		}
		if err != nil {
			writeJSON(w, http.StatusConflict, map[string]string{"code": "UNKNOWN_RETRY_NOT_AUTHORIZED"})
			return
		}
		value, _ := scopeStatus(r.Context(), runtime.Database, r.PathValue("scope"))
		writeJSON(w, http.StatusOK, value)
	})))
}

type decision struct {
	IntentID             string `json:"intentId"`
	RawSHA256            string `json:"rawSha256"`
	RawSize              int64  `json:"rawSize"`
	Sender               string `json:"sender"`
	Recipient            string `json:"recipient"`
	ConfirmDuplicateRisk bool   `json:"confirmDuplicateRisk"`
	RequestKey           string `json:"requestKey"`
}

func decodeDecision(r *http.Request) (decision, error) {
	var value decision
	decoder := json.NewDecoder(io.LimitReader(r.Body, 16*1024))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil || !validUUID(value.IntentID) || len(value.RawSHA256) != 64 || value.RawSize < 1 || value.RawSize > 5*1024*1024 {
		return decision{}, errBadDecision
	}
	return value, nil
}

func cancelScope(ctx context.Context, runtime *platform.Runtime, scope string, input decision) error {
	if !validUUID(scope) {
		return errBadDecision
	}
	return runtime.Witness.Write(ctx, "delivery-cancel|"+scope+"|"+input.IntentID, func(tx *sql.Tx) error {
		var intent, state, raw, sender string
		var size int64
		var started bool
		err := tx.QueryRowContext(ctx, "SELECT source_intent_id,state,ever_started,raw_sha256,raw_size,sender_address FROM dispatch_scopes WHERE scope_id=? FOR UPDATE", scope).Scan(&intent, &state, &started, &raw, &size, &sender)
		if errors.Is(err, sql.ErrNoRows) {
			_, err = tx.ExecContext(ctx, `INSERT INTO dispatch_scopes(scope_id,source_intent_id,source_service,raw_sha256,raw_size,sender_address,state) VALUES(?,?,'mailbox',?,?,?,'CANCELLED')`, scope, input.IntentID, input.RawSHA256, input.RawSize, input.Sender)
			return err
		}
		if err != nil || intent != input.IntentID || raw != input.RawSHA256 || size != input.RawSize || !strings.EqualFold(sender, input.Sender) {
			return errBadDecision
		}
		if state == "CANCELLED" {
			return nil
		}
		if started || state != "QUEUED" {
			return errSendStarted
		}
		if _, err := tx.ExecContext(ctx, "UPDATE dispatch_scopes SET state='CANCELLED',version_no=version_no+1 WHERE scope_id=?", scope); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, "UPDATE delivery_jobs SET state='CANCELLED',worker_id=NULL,lease_until=NULL WHERE scope_id=? AND state IN('QUEUED','RETRY_WAIT')", scope)
		return err
	})
}

func retryUnknown(ctx context.Context, runtime *platform.Runtime, scope string, input decision) error {
	return runtime.Witness.Write(ctx, "delivery-retry-unknown|"+scope+"|"+input.RequestKey, func(tx *sql.Tx) error {
		var existing string
		if err := tx.QueryRowContext(ctx, "SELECT recipient FROM delivery_retry_requests WHERE scope_id=? AND request_key=? FOR UPDATE", scope, input.RequestKey).Scan(&existing); err == nil {
			if input.Recipient == "" || strings.EqualFold(existing, input.Recipient) {
				return nil
			}
			return errBadDecision
		} else if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		var job, recipient string
		query := "SELECT job_id,recipient FROM delivery_jobs WHERE scope_id=? AND state='UNKNOWN'"
		arguments := []any{scope}
		if input.Recipient != "" {
			query += " AND recipient=?"
			arguments = append(arguments, strings.ToLower(input.Recipient))
		}
		query += " ORDER BY job_id LIMIT 2 FOR UPDATE"
		rows, err := tx.QueryContext(ctx, query, arguments...)
		if err != nil {
			return err
		}
		matches := 0
		for rows.Next() {
			matches++
			if err := rows.Scan(&job, &recipient); err != nil {
				rows.Close()
				return err
			}
		}
		rows.Close()
		if matches != 1 {
			return errBadDecision
		}
		var prior string
		if err := tx.QueryRowContext(ctx, "SELECT attempt_id FROM delivery_attempts WHERE job_id=? AND outcome='UNKNOWN' ORDER BY epoch_no DESC LIMIT 1 FOR UPDATE", job).Scan(&prior); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE delivery_jobs SET state='QUEUED',next_attempt_at=CURRENT_TIMESTAMP(6) WHERE job_id=? AND state='UNKNOWN'`, job); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE dispatch_scopes SET state='QUEUED',version_no=version_no+1 WHERE scope_id=?`, scope); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, "INSERT INTO delivery_retry_requests(scope_id,request_key,recipient,prior_attempt_id) VALUES(?,?,?,?)", scope, input.RequestKey, recipient, prior)
		return err
	})
}

func scopeStatus(ctx context.Context, database *sql.DB, scope string) (map[string]any, error) {
	var intent, state string
	var started bool
	var version int64
	if err := database.QueryRowContext(ctx, "SELECT source_intent_id,state,ever_started,version_no FROM dispatch_scopes WHERE scope_id=?", scope).Scan(&intent, &state, &started, &version); err != nil {
		return nil, err
	}
	jobs, err := database.QueryContext(ctx, "SELECT job_id,recipient,state,attempt_count FROM delivery_jobs WHERE scope_id=? ORDER BY recipient", scope)
	if err != nil {
		return nil, err
	}
	defer jobs.Close()
	items := []map[string]any{}
	for jobs.Next() {
		var job, recipient, jobState string
		var count int
		if err := jobs.Scan(&job, &recipient, &jobState, &count); err != nil {
			return nil, err
		}
		attemptRows, err := database.QueryContext(ctx, `SELECT attempt_id,epoch_no,last_stage,data_submitted,smtp_code,outcome,evidence_sha256,duplicate_risk_ack,prior_attempt_id,started_at,completed_at FROM delivery_attempts WHERE job_id=? ORDER BY epoch_no`, job)
		if err != nil {
			return nil, err
		}
		attempts := []map[string]any{}
		for attemptRows.Next() {
			var id, stage string
			var epoch int64
			var submitted, duplicate bool
			var code sql.NullInt64
			var outcome, evidence, prior sql.NullString
			var startedAt time.Time
			var completed sql.NullTime
			if err := attemptRows.Scan(&id, &epoch, &stage, &submitted, &code, &outcome, &evidence, &duplicate, &prior, &startedAt, &completed); err != nil {
				attemptRows.Close()
				return nil, err
			}
			attempts = append(attempts, map[string]any{"id": id, "epoch": epoch, "lastStage": stage, "dataSubmitted": submitted, "smtpCode": nullableInt(code), "outcome": nullableString(outcome), "evidenceSha256": nullableString(evidence), "duplicateRiskAcknowledged": duplicate, "priorAttemptId": nullableString(prior), "startedAt": startedAt, "completedAt": nullableTime(completed)})
		}
		attemptRows.Close()
		items = append(items, map[string]any{"id": job, "recipient": recipient, "state": jobState, "attemptCount": count, "attempts": attempts})
	}
	return map[string]any{"id": scope, "intentId": intent, "state": state, "everStarted": started, "version": version, "recipients": items}, jobs.Err()
}

func nullableString(value sql.NullString) any {
	if value.Valid {
		return value.String
	}
	return nil
}
func nullableInt(value sql.NullInt64) any {
	if value.Valid {
		return value.Int64
	}
	return nil
}
func nullableTime(value sql.NullTime) any {
	if value.Valid {
		return value.Time
	}
	return nil
}

func validUUID(value string) bool {
	_, err := uuid.Parse(value)
	return err == nil
}

func internal(runtime *platform.Runtime, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := runtime.RequireInternal(r.Header.Get("X-GuiHong-Service"), r.Header.Get("Authorization")); err != nil {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json;charset=UTF-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
