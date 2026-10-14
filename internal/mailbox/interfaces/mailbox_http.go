package interfaces

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/application"
	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

type draftBody struct {
	Version         *int64           `json:"version"`
	Subject         string           `json:"subject"`
	TextBody        string           `json:"textBody"`
	HTMLBody        string           `json:"htmlBody"`
	To              []string         `json:"to"`
	CC              []string         `json:"cc"`
	BCC             []string         `json:"bcc"`
	Mode            domain.DraftMode `json:"mode"`
	SourceContentID *string          `json:"sourceContentId"`
}

func RegisterWeb(mux *http.ServeMux, root string) {
	rootPath, err := filepath.Abs(root)
	if err != nil {
		panic(err)
	}
	index := filepath.Join(rootPath, "index.html")
	mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
		requested := filepath.Join(rootPath, filepath.FromSlash(strings.TrimPrefix(r.URL.Path, "/")))
		if relative, err := filepath.Rel(rootPath, requested); err != nil || strings.HasPrefix(relative, "..") {
			apiError(w, http.StatusNotFound, "RESOURCE_NOT_FOUND")
			return
		}
		if info, err := os.Stat(requested); err == nil && !info.IsDir() {
			http.ServeFile(w, r, requested)
			return
		}
		if _, err := os.Stat(index); err != nil {
			apiError(w, http.StatusServiceUnavailable, "WEB_ASSETS_UNAVAILABLE")
			return
		}
		http.ServeFile(w, r, index)
	})
}

func RegisterMailbox(mux *http.ServeMux, runtime *platform.Runtime, identity *application.Identity, mailbox *application.Mailbox) {
	read := func(handler http.HandlerFunc) http.Handler { return authenticated(identity, false, handler) }
	write := func(handler http.HandlerFunc) http.Handler { return authenticated(identity, true, handler) }
	mux.Handle("GET /api/mailbox/folders", read(func(w http.ResponseWriter, r *http.Request) {
		value, err := mailbox.FolderCounts(r.Context(), principal(r).AccountID)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("GET /api/mailbox/messages", read(func(w http.ResponseWriter, r *http.Request) {
		var folder *domain.Folder
		if value := r.URL.Query().Get("folder"); value != "" {
			f := domain.Folder(strings.ToUpper(value))
			folder = &f
		}
		var category *string
		if value := r.URL.Query().Get("category_id"); value != "" {
			category = &value
		}
		size, err := queryInt(r, "size", 30)
		if err != nil {
			mailboxError(w, &domain.InvalidError{Code: "INVALID_PAGE_SIZE"})
			return
		}
		value, failure := mailbox.List(r.Context(), principal(r).AccountID, folder, category, r.URL.Query().Get("q"), size, r.URL.Query().Get("cursor"))
		mailboxResponse(w, value, failure, http.StatusOK)
	}))
	mux.Handle("GET /api/mailbox/messages/{entry}", read(func(w http.ResponseWriter, r *http.Request) {
		value, err := mailbox.Message(r.Context(), principal(r).AccountID, r.PathValue("entry"))
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("PATCH /api/mailbox/messages/{entry}", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Version       *int64         `json:"version"`
			Read          *bool          `json:"read"`
			Folder        *domain.Folder `json:"folder"`
			CategoryID    *string        `json:"categoryId"`
			ClearCategory bool           `json:"clearCategory"`
		}
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		change := domain.MessageChange{ExpectedVersion: body.Version, Read: body.Read, Folder: body.Folder, CategoryID: body.CategoryID, CategorySet: body.CategoryID != nil || body.ClearCategory}
		value, err := mailbox.Change(r.Context(), principal(r).AccountID, r.PathValue("entry"), change)
		mailboxResponse(w, value, err, http.StatusOK)
	}))

	mux.Handle("GET /api/mailbox/drafts", read(func(w http.ResponseWriter, r *http.Request) {
		size, err := queryInt(r, "size", 30)
		if err != nil {
			mailboxError(w, &domain.InvalidError{Code: "INVALID_PAGE_SIZE"})
			return
		}
		value, failure := mailbox.Drafts(r.Context(), principal(r).AccountID, size, r.URL.Query().Get("cursor"))
		mailboxResponse(w, value, failure, http.StatusOK)
	}))
	mux.Handle("POST /api/mailbox/drafts", write(func(w http.ResponseWriter, r *http.Request) {
		var body draftBody
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := mailbox.CreateDraft(r.Context(), principal(r).AccountID, draftInput(body))
		mailboxResponse(w, value, err, http.StatusCreated)
	}))
	mux.Handle("GET /api/mailbox/drafts/{draft}", read(func(w http.ResponseWriter, r *http.Request) {
		value, err := mailbox.Draft(r.Context(), principal(r).AccountID, r.PathValue("draft"))
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("PUT /api/mailbox/drafts/{draft}", write(func(w http.ResponseWriter, r *http.Request) {
		var body draftBody
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		version := int64(0)
		if body.Version != nil {
			version = *body.Version
		}
		value, err := mailbox.UpdateDraft(r.Context(), principal(r).AccountID, r.PathValue("draft"), version, draftInput(body))
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("DELETE /api/mailbox/drafts/{draft}", write(func(w http.ResponseWriter, r *http.Request) {
		version, err := queryInt64(r, "version")
		if err != nil {
			mailboxError(w, &domain.InvalidError{Code: "INVALID_VERSION"})
			return
		}
		err = mailbox.DeleteDraft(r.Context(), principal(r).AccountID, r.PathValue("draft"), version)
		if err != nil {
			mailboxError(w, err)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	mux.Handle("POST /api/mailbox/messages/{entry}/drafts", write(func(w http.ResponseWriter, r *http.Request) {
		value, err := mailbox.DeriveDraft(r.Context(), principal(r).AccountID, r.PathValue("entry"), domain.DraftMode(strings.ToUpper(r.URL.Query().Get("mode"))))
		mailboxResponse(w, value, err, http.StatusCreated)
	}))
	mux.Handle("POST /api/mailbox/drafts/{draft}/attachments", write(func(w http.ResponseWriter, r *http.Request) {
		version, err := queryInt64(r, "version")
		if err != nil {
			mailboxError(w, &domain.InvalidError{Code: "INVALID_VERSION"})
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, 4*1024*1024+64*1024)
		file, header, err := r.FormFile("file")
		if err != nil {
			mailboxError(w, &domain.InvalidError{Code: "ATTACHMENT_SIZE_EXCEEDED"})
			return
		}
		defer file.Close()
		_, disposition, parseError := mime.ParseMediaType(header.Header.Get("Content-Disposition"))
		if parseError != nil || disposition["filename"] != header.Filename {
			mailboxError(w, &domain.InvalidError{Code: "INVALID_FILE_NAME"})
			return
		}
		data, err := io.ReadAll(io.LimitReader(file, 4*1024*1024+1))
		if err != nil || len(data) > 4*1024*1024 {
			mailboxError(w, &domain.InvalidError{Code: "ATTACHMENT_SIZE_EXCEEDED"})
			return
		}
		value, failure := mailbox.Attach(r.Context(), principal(r).AccountID, r.PathValue("draft"), version, header.Filename, header.Header.Get("Content-Type"), data)
		mailboxResponse(w, value, failure, http.StatusCreated)
	}))
	mux.Handle("GET /api/mailbox/messages/{entry}/attachments/{attachment}", read(func(w http.ResponseWriter, r *http.Request) {
		meta, data, err := mailbox.MessageAttachment(r.Context(), principal(r).AccountID, r.PathValue("entry"), r.PathValue("attachment"))
		download(w, meta, data, err)
	}))
	mux.Handle("GET /api/mailbox/drafts/{draft}/attachments/{attachment}", read(func(w http.ResponseWriter, r *http.Request) {
		meta, data, err := mailbox.DraftAttachment(r.Context(), principal(r).AccountID, r.PathValue("draft"), r.PathValue("attachment"))
		download(w, meta, data, err)
	}))

	mux.Handle("GET /api/mailbox/categories", read(func(w http.ResponseWriter, r *http.Request) {
		value, err := mailbox.Categories(r.Context(), principal(r).AccountID)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("POST /api/mailbox/categories", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Name string `json:"name"`
		}
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := mailbox.CreateCategory(r.Context(), principal(r).AccountID, body.Name)
		mailboxResponse(w, value, err, http.StatusCreated)
	}))
	mux.Handle("PUT /api/mailbox/categories/{category}", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Version int64  `json:"version"`
			Name    string `json:"name"`
		}
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := mailbox.RenameCategory(r.Context(), principal(r).AccountID, r.PathValue("category"), body.Version, body.Name)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("DELETE /api/mailbox/categories/{category}", write(func(w http.ResponseWriter, r *http.Request) {
		version, err := queryInt64(r, "version")
		if err != nil {
			mailboxError(w, &domain.InvalidError{Code: "INVALID_VERSION"})
			return
		}
		err = mailbox.DeleteCategory(r.Context(), principal(r).AccountID, r.PathValue("category"), version)
		if err != nil {
			mailboxError(w, err)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))

	mux.Handle("POST /internal/mailbox/fixtures", internal(runtime, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Base64  string `json:"base64"`
			Members []struct {
				AccountID string        `json:"accountId"`
				Folder    domain.Folder `json:"folder"`
				Read      bool          `json:"read"`
			} `json:"members"`
		}
		if err := decode(r, &body); err != nil || len(body.Base64) > 7*1024*1024 {
			mailboxError(w, &domain.InvalidError{Code: "MIME_SIZE_EXCEEDED"})
			return
		}
		raw, err := base64.StdEncoding.DecodeString(body.Base64)
		if err != nil {
			mailboxError(w, &domain.InvalidError{Code: "MIME_BASE64_INVALID"})
			return
		}
		members := make([]domain.Member, 0, len(body.Members))
		for _, member := range body.Members {
			members = append(members, domain.Member{AccountID: member.AccountID, Folder: member.Folder, Read: member.Read})
		}
		id, failure := mailbox.ImportMIME(r.Context(), raw, members)
		mailboxResponse(w, map[string]string{"content_id": id}, failure, http.StatusOK)
	})))
}

func RegisterClassification(mux *http.ServeMux, identity *application.Identity, classifier *application.Classifier) {
	read := func(handler http.HandlerFunc) http.Handler { return authenticated(identity, false, handler) }
	write := func(handler http.HandlerFunc) http.Handler { return authenticated(identity, true, handler) }
	mux.Handle("GET /api/mailbox/classification/rules", read(func(w http.ResponseWriter, r *http.Request) {
		value, err := classifier.Rules(r.Context(), principal(r).AccountID)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("POST /api/mailbox/classification/rules", write(func(w http.ResponseWriter, r *http.Request) {
		var body domain.ClassificationRule
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := classifier.CreateRule(r.Context(), principal(r).AccountID, body)
		mailboxResponse(w, value, err, http.StatusCreated)
	}))
	mux.Handle("PUT /api/mailbox/classification/rules/{rule}", write(func(w http.ResponseWriter, r *http.Request) {
		var body domain.ClassificationRule
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		body.ID = r.PathValue("rule")
		value, err := classifier.UpdateRule(r.Context(), principal(r).AccountID, body)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("DELETE /api/mailbox/classification/rules/{rule}", write(func(w http.ResponseWriter, r *http.Request) {
		version, err := queryInt64(r, "version")
		if err != nil {
			mailboxError(w, &domain.InvalidError{Code: "INVALID_VERSION"})
			return
		}
		if err = classifier.DeleteRule(r.Context(), principal(r).AccountID, r.PathValue("rule"), version); err != nil {
			mailboxError(w, err)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	mux.Handle("GET /api/mailbox/classification/settings", read(func(w http.ResponseWriter, r *http.Request) {
		value, err := classifier.Settings(r.Context(), principal(r).AccountID)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("PUT /api/mailbox/classification/settings", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Version          int64 `json:"version"`
			AlgorithmEnabled bool  `json:"algorithmEnabled"`
		}
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := classifier.SetAlgorithmEnabled(r.Context(), principal(r).AccountID, body.Version, body.AlgorithmEnabled)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("PUT /api/mailbox/classification/category-auto/{category}", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Enabled bool `json:"enabled"`
		}
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := classifier.SetCategoryAuto(r.Context(), principal(r).AccountID, r.PathValue("category"), body.Enabled)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("GET /api/mailbox/messages/{entry}/classification", read(func(w http.ResponseWriter, r *http.Request) {
		value, err := classifier.Evaluate(r.Context(), principal(r).AccountID, r.PathValue("entry"))
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("POST /api/mailbox/messages/{entry}/classification/decision", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			SuggestionID string `json:"suggestionId"`
			Decision     string `json:"decision"`
			Version      int64  `json:"version"`
		}
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := classifier.Decide(r.Context(), principal(r).AccountID, r.PathValue("entry"), body.SuggestionID, body.Decision, body.Version)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
	mux.Handle("POST /api/mailbox/messages/{entry}/classification/undo", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			ActionID string `json:"actionId"`
			Version  int64  `json:"version"`
		}
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := classifier.Undo(r.Context(), principal(r).AccountID, r.PathValue("entry"), body.ActionID, body.Version)
		mailboxResponse(w, value, err, http.StatusOK)
	}))
}

func RegisterSend(mux *http.ServeMux, runtime *platform.Runtime, identity *application.Identity, sender *application.Sender, sends domain.SendRepository) {
	read := func(handler http.HandlerFunc) http.Handler { return authenticated(identity, false, handler) }
	write := func(handler http.HandlerFunc) http.Handler { return authenticated(identity, true, handler) }
	mux.Handle("POST /api/mailbox/drafts/{draft}/send", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Version int64 `json:"version"`
		}
		if err := decode(r, &body); err != nil {
			mailboxError(w, &domain.InvalidError{Code: "REQUEST_MALFORMED"})
			return
		}
		value, err := sender.Submit(r.Context(), principal(r).AccountID, r.PathValue("draft"), body.Version, r.Header.Get("Idempotency-Key"))
		mailboxResponse(w, value, err, http.StatusAccepted)
	}))
	mux.Handle("GET /api/mailbox/send-intents/{intent}", read(func(w http.ResponseWriter, r *http.Request) {
		intent, err := sender.Intent(r.Context(), principal(r).AccountID, r.PathValue("intent"))
		if err != nil {
			mailboxError(w, err)
			return
		}
		status, body, err := platform.InternalRequest(r.Context(), runtime, http.MethodGet, "http://127.0.0.1:18082/internal/dispatch-scopes/"+intent.DispatchScopeID, nil, 128*1024)
		if err != nil || (status != http.StatusOK && status != http.StatusNotFound) {
			mailboxError(w, errors.New("delivery status unavailable"))
			return
		}
		response := map[string]any{"intent": intent}
		if status == http.StatusOK {
			var delivery any
			if json.Unmarshal(body, &delivery) != nil {
				mailboxError(w, errors.New("delivery status invalid"))
				return
			}
			response["delivery"] = delivery
		}
		writeAPI(w, http.StatusOK, response)
	}))
	mux.Handle("POST /api/mailbox/send-intents/{intent}/cancel", write(func(w http.ResponseWriter, r *http.Request) {
		forwardDeliveryDecision(w, r, runtime, sender, "/cancel", nil)
	}))
	mux.Handle("POST /api/mailbox/send-intents/{intent}/retry-unknown", write(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			ConfirmDuplicateRisk bool   `json:"confirmDuplicateRisk"`
			Recipient            string `json:"recipient"`
		}
		if err := decode(r, &body); err != nil || !body.ConfirmDuplicateRisk {
			mailboxError(w, &domain.InvalidError{Code: "DUPLICATE_RISK_CONFIRMATION_REQUIRED"})
			return
		}
		forwardDeliveryDecision(w, r, runtime, sender, "/retry-unknown", map[string]any{"confirmDuplicateRisk": true, "recipient": body.Recipient, "requestKey": r.Header.Get("Idempotency-Key")})
	}))
	mux.Handle("GET /internal/admission", internal(runtime, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		account, err := sends.EnabledAccount(r.Context(), strings.ToLower(strings.TrimSpace(r.URL.Query().Get("address"))))
		if err != nil {
			mailboxError(w, err)
			return
		}
		writeAPI(w, http.StatusOK, map[string]string{"accountId": account})
	})))
	mux.Handle("GET /internal/send-intents/{intent}/raw", internal(runtime, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, digest, err := sender.Raw(r.Context(), r.PathValue("intent"))
		if err != nil {
			mailboxError(w, err)
			return
		}
		w.Header().Set("Content-Type", "message/rfc822")
		w.Header().Set("X-GuiHong-SHA256", digest)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(raw)
	})))
}

func forwardDeliveryDecision(w http.ResponseWriter, r *http.Request, runtime *platform.Runtime, sender *application.Sender, suffix string, extra map[string]any) {
	intent, err := sender.Intent(r.Context(), principal(r).AccountID, r.PathValue("intent"))
	if err != nil {
		mailboxError(w, err)
		return
	}
	payload := map[string]any{"intentId": intent.ID, "rawSha256": intent.RawSHA256, "rawSize": intent.RawSize, "sender": intent.SenderAddress}
	for key, value := range extra {
		payload[key] = value
	}
	status, body, failure := platform.InternalRequest(r.Context(), runtime, http.MethodPost, "http://127.0.0.1:18082/internal/dispatch-scopes/"+intent.DispatchScopeID+suffix, payload, 128*1024)
	if failure != nil {
		mailboxError(w, failure)
		return
	}
	if status == http.StatusConflict {
		w.Header().Set("Content-Type", "application/json;charset=UTF-8")
		w.WriteHeader(status)
		_, _ = w.Write(body)
		return
	}
	if status < 200 || status >= 300 {
		mailboxError(w, errors.New("delivery decision unavailable"))
		return
	}
	w.Header().Set("Content-Type", "application/json;charset=UTF-8")
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

func draftInput(body draftBody) domain.DraftInput {
	return domain.DraftInput{Subject: body.Subject, TextBody: body.TextBody, HTMLBody: body.HTMLBody, To: body.To, CC: body.CC, BCC: body.BCC, Mode: body.Mode, SourceContentID: body.SourceContentID}
}
func queryInt(r *http.Request, name string, fallback int) (int, error) {
	value := r.URL.Query().Get(name)
	if value == "" {
		return fallback, nil
	}
	return strconv.Atoi(value)
}
func queryInt64(r *http.Request, name string) (int64, error) {
	return strconv.ParseInt(r.URL.Query().Get(name), 10, 64)
}
func mailboxResponse(w http.ResponseWriter, value any, err error, status int) {
	if err != nil {
		mailboxError(w, err)
		return
	}
	writeAPI(w, status, value)
}
func mailboxError(w http.ResponseWriter, err error) {
	var invalid *domain.InvalidError
	var conflict *domain.VersionConflictError
	var unknown *platform.CommitUnknownError
	switch {
	case errors.Is(err, domain.ErrNotFound):
		apiError(w, http.StatusNotFound, "RESOURCE_NOT_FOUND")
	case errors.As(err, &invalid):
		apiError(w, http.StatusBadRequest, invalid.Code)
	case errors.As(err, &conflict):
		writeAPI(w, http.StatusConflict, map[string]any{"code": "VERSION_CONFLICT", "current_version": conflict.Current})
	case errors.Is(err, domain.ErrIdempotencyConflict):
		apiError(w, http.StatusConflict, "IDEMPOTENCY_CONFLICT")
	case errors.As(err, &unknown):
		apiError(w, http.StatusServiceUnavailable, "COMMIT_OUTCOME_UNKNOWN")
	default:
		apiError(w, http.StatusServiceUnavailable, "SERVICE_UNAVAILABLE")
	}
}
func download(w http.ResponseWriter, meta domain.Attachment, data []byte, err error) {
	if err != nil {
		mailboxError(w, err)
		return
	}
	mediaType := meta.MediaType
	if _, _, parseErr := mime.ParseMediaType(mediaType); parseErr != nil {
		mediaType = "application/octet-stream"
	}
	w.Header().Set("Content-Type", mediaType)
	w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename*=UTF-8''%s", strings.ReplaceAll(meta.FileName, " ", "%20")))
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(data)
}
