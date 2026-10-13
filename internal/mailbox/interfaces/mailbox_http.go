package interfaces

import (
	"encoding/base64"
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
