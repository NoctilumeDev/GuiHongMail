package application

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
	"github.com/google/uuid"
)

const maxMailboxBytes = 5 * 1024 * 1024

var mailboxAddress = regexp.MustCompile(`^[^\s@]{1,64}@[^\s@]{1,189}$`)
var mediaType = regexp.MustCompile(`^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$`)

type MessageParser interface {
	Parse([]byte) (domain.ParsedMessage, error)
}
type HTMLSanitizer interface{ Sanitize(string) string }

type Mailbox struct {
	repository domain.MailboxRepository
	parser     MessageParser
	sanitizer  HTMLSanitizer
	objects    *platform.ObjectRepository
}

func NewMailbox(repository domain.MailboxRepository, parser MessageParser, sanitizer HTMLSanitizer, objects *platform.ObjectRepository) *Mailbox {
	return &Mailbox{repository: repository, parser: parser, sanitizer: sanitizer, objects: objects}
}
func (m *Mailbox) available(ctx context.Context) error {
	if !m.repository.Available(ctx) {
		return errors.New("SERVICE_UNAVAILABLE")
	}
	return nil
}
func validateID(value string) error {
	if _, err := uuid.Parse(value); err != nil {
		return &domain.InvalidError{Code: "INVALID_ID"}
	}
	return nil
}

func (m *Mailbox) ImportMIME(ctx context.Context, raw []byte, members []domain.Member) (string, error) {
	if err := m.available(ctx); err != nil {
		return "", err
	}
	if len(raw) == 0 || len(raw) > maxMailboxBytes {
		return "", &domain.InvalidError{Code: "MIME_SIZE_EXCEEDED"}
	}
	if len(members) == 0 || len(members) > 10 {
		return "", &domain.InvalidError{Code: "INVALID_MEMBERS"}
	}
	seen := map[string]bool{}
	for _, member := range members {
		if validateID(member.AccountID) != nil || !member.Folder.Valid() || seen[member.AccountID] {
			return "", &domain.InvalidError{Code: "INVALID_MEMBERS"}
		}
		seen[member.AccountID] = true
	}
	parsed, err := m.parser.Parse(raw)
	if err != nil {
		return "", err
	}
	if len(parsed.Attachments) > 20 {
		return "", &domain.InvalidError{Code: "MIME_PART_LIMIT"}
	}
	total := 0
	for _, a := range parsed.Attachments {
		total += len(a.Bytes)
	}
	if total > 4*1024*1024 {
		return "", &domain.InvalidError{Code: "ATTACHMENT_TOTAL_EXCEEDED"}
	}
	contentID := uuid.NewString()
	type ref struct{ id, kind, reference string }
	refs := []ref{}
	store := func(data []byte, authority, kind, reference string) (platform.Blob, error) {
		id := uuid.NewString()
		blob, err := m.objects.Stage(ctx, id, authority, data)
		if err != nil {
			return platform.Blob{}, err
		}
		blob, err = m.objects.Reference(ctx, id, kind, reference)
		if err == nil {
			refs = append(refs, ref{id, kind, reference})
		}
		return blob, err
	}
	rawBlob, err := store(raw, "message:"+contentID, "MESSAGE_RAW", contentID)
	if err != nil {
		return "", err
	}
	stored := []domain.StoredAttachment{}
	cleanup := func() {
		for index := len(refs) - 1; index >= 0; index-- {
			_ = m.objects.Dereference(ctx, refs[index].id, refs[index].kind, refs[index].reference)
		}
	}
	for _, part := range parsed.Attachments {
		attachmentID := uuid.NewString()
		blob, storeErr := store(part.Bytes, "message-attachment:"+attachmentID, "MESSAGE_ATTACHMENT", attachmentID)
		if storeErr != nil {
			cleanup()
			return "", storeErr
		}
		stored = append(stored, domain.StoredAttachment{ID: attachmentID, ObjectID: blob.ID, FileName: part.FileName, MediaType: part.MediaType, SHA256: blob.SHA256, Size: blob.Size})
	}
	message := domain.ImportedMessage{ContentID: contentID, RawObjectID: rawBlob.ID, RawSHA256: rawBlob.SHA256, RawSize: rawBlob.Size, Parsed: parsed, Attachments: stored}
	if err = m.repository.ImportMessage(ctx, message, members); err != nil {
		var unknown *platform.CommitUnknownError
		if !errors.As(err, &unknown) {
			cleanup()
		}
		return "", err
	}
	return contentID, nil
}

func (m *Mailbox) FolderCounts(ctx context.Context, account string) ([]domain.FolderCount, error) {
	if err := validateID(account); err != nil {
		return nil, err
	}
	return m.repository.FolderCounts(ctx, account)
}
func (m *Mailbox) List(ctx context.Context, account string, folder *domain.Folder, category *string, query string, size int, cursor string) (domain.Page[domain.MessageSummary], error) {
	if err := validateID(account); err != nil {
		return domain.Page[domain.MessageSummary]{}, err
	}
	if (folder == nil) == (category == nil) {
		return domain.Page[domain.MessageSummary]{}, &domain.InvalidError{Code: "FOLDER_OR_CATEGORY_REQUIRED"}
	}
	if folder != nil && !folder.Valid() {
		return domain.Page[domain.MessageSummary]{}, &domain.InvalidError{Code: "INVALID_FOLDER"}
	}
	if category != nil {
		if err := validateID(*category); err != nil {
			return domain.Page[domain.MessageSummary]{}, err
		}
	}
	if size < 1 || size > 100 {
		return domain.Page[domain.MessageSummary]{}, &domain.InvalidError{Code: "INVALID_PAGE_SIZE"}
	}
	if len([]rune(query)) > 200 {
		return domain.Page[domain.MessageSummary]{}, &domain.InvalidError{Code: "SEARCH_TOO_LONG"}
	}
	return m.repository.List(ctx, account, folder, category, strings.TrimSpace(query), size, cursor)
}
func (m *Mailbox) Message(ctx context.Context, account, entry string) (domain.MessageDetail, error) {
	if err := validatePair(account, entry); err != nil {
		return domain.MessageDetail{}, err
	}
	return m.repository.Message(ctx, account, entry)
}
func (m *Mailbox) Change(ctx context.Context, account, entry string, change domain.MessageChange) (domain.MessageDetail, error) {
	if err := validatePair(account, entry); err != nil {
		return domain.MessageDetail{}, err
	}
	if change.Folder != nil && !change.Folder.Valid() {
		return domain.MessageDetail{}, &domain.InvalidError{Code: "INVALID_FOLDER"}
	}
	if change.CategoryID != nil {
		if err := validateID(*change.CategoryID); err != nil {
			return domain.MessageDetail{}, err
		}
	}
	return m.repository.Change(ctx, account, entry, change)
}

func (m *Mailbox) CreateDraft(ctx context.Context, account string, input domain.DraftInput) (domain.Draft, error) {
	if err := validateID(account); err != nil {
		return domain.Draft{}, err
	}
	validated, err := m.validateDraft(input)
	if err != nil {
		return domain.Draft{}, err
	}
	return m.repository.CreateDraft(ctx, account, validated)
}
func (m *Mailbox) Draft(ctx context.Context, account, id string) (domain.Draft, error) {
	if err := validatePair(account, id); err != nil {
		return domain.Draft{}, err
	}
	return m.repository.Draft(ctx, account, id)
}
func (m *Mailbox) Drafts(ctx context.Context, account string, size int, cursor string) (domain.Page[domain.Draft], error) {
	if err := validateID(account); err != nil {
		return domain.Page[domain.Draft]{}, err
	}
	if size < 1 || size > 100 {
		return domain.Page[domain.Draft]{}, &domain.InvalidError{Code: "INVALID_PAGE_SIZE"}
	}
	return m.repository.Drafts(ctx, account, size, cursor)
}
func (m *Mailbox) UpdateDraft(ctx context.Context, account, id string, version int64, input domain.DraftInput) (domain.Draft, error) {
	if err := validatePair(account, id); err != nil {
		return domain.Draft{}, err
	}
	if version < 1 {
		return domain.Draft{}, &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	validated, err := m.validateDraft(input)
	if err != nil {
		return domain.Draft{}, err
	}
	return m.repository.UpdateDraft(ctx, account, id, version, validated)
}
func (m *Mailbox) DeleteDraft(ctx context.Context, account, id string, version int64) error {
	if err := validatePair(account, id); err != nil {
		return err
	}
	if version < 1 {
		return &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	attachments, err := m.repository.DeleteDraft(ctx, account, id, version)
	if err != nil {
		return err
	}
	for _, a := range attachments {
		if err := m.objects.Dereference(ctx, a.ObjectID, "DRAFT_ATTACHMENT", a.ID); err != nil {
			return err
		}
	}
	return nil
}
func (m *Mailbox) DeriveDraft(ctx context.Context, account, entry string, mode domain.DraftMode) (domain.Draft, error) {
	if mode != domain.Reply && mode != domain.ReplyAll && mode != domain.Forward {
		return domain.Draft{}, &domain.InvalidError{Code: "INVALID_DRAFT_MODE"}
	}
	source, err := m.Message(ctx, account, entry)
	if err != nil {
		return domain.Draft{}, err
	}
	own, err := m.repository.AccountAddress(ctx, account)
	if err != nil {
		return domain.Draft{}, err
	}
	to := []string{}
	cc := []string{}
	if mode == domain.Reply || mode == domain.ReplyAll {
		to = append(to, source.Summary.FromAddress)
	}
	if mode == domain.ReplyAll {
		for _, recipient := range source.Recipients {
			if recipient.Kind == "BCC" || strings.EqualFold(recipient.Address, own) || containsAddress(to, recipient.Address) || containsAddress(cc, recipient.Address) {
				continue
			}
			if recipient.Kind == "TO" {
				to = append(to, recipient.Address)
			} else {
				cc = append(cc, recipient.Address)
			}
		}
	}
	subject := source.Summary.Subject
	text := "\n\n" + source.TextBody
	if mode == domain.Forward {
		subject = prefix(subject, "Fwd: ")
		text = "\n\n--- Forwarded message ---\n" + source.TextBody
	} else {
		subject = prefix(subject, "Re: ")
	}
	input := domain.DraftInput{Subject: subject, TextBody: text, To: to, CC: cc, BCC: []string{}, Mode: mode, SourceContentID: &source.Summary.ContentID}
	return m.CreateDraft(ctx, account, input)
}

func (m *Mailbox) Attach(ctx context.Context, account, draft string, version int64, file, media string, data []byte) (domain.Draft, error) {
	if err := validatePair(account, draft); err != nil {
		return domain.Draft{}, err
	}
	if version < 1 {
		return domain.Draft{}, &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	safe, err := validateFileName(file)
	if err != nil {
		return domain.Draft{}, err
	}
	media = strings.ToLower(strings.TrimSpace(media))
	if !mediaType.MatchString(media) {
		media = "application/octet-stream"
	}
	if len(data) > 4*1024*1024 {
		return domain.Draft{}, &domain.InvalidError{Code: "ATTACHMENT_SIZE_EXCEEDED"}
	}
	id := uuid.NewString()
	blob, err := m.objects.Stage(ctx, uuid.NewString(), "draft-attachment:"+id, data)
	if err != nil {
		return domain.Draft{}, err
	}
	blob, err = m.objects.Reference(ctx, blob.ID, "DRAFT_ATTACHMENT", id)
	if err != nil {
		return domain.Draft{}, err
	}
	result, err := m.repository.AddDraftAttachment(ctx, account, draft, version, domain.StoredAttachment{ID: id, ObjectID: blob.ID, FileName: safe, MediaType: media, SHA256: blob.SHA256, Size: blob.Size})
	if err != nil {
		var unknown *platform.CommitUnknownError
		if !errors.As(err, &unknown) {
			_ = m.objects.Dereference(ctx, blob.ID, "DRAFT_ATTACHMENT", id)
		}
		return domain.Draft{}, err
	}
	return result, nil
}
func (m *Mailbox) MessageAttachment(ctx context.Context, account, entry, id string) (domain.Attachment, []byte, error) {
	if err := validateTriple(account, entry, id); err != nil {
		return domain.Attachment{}, nil, err
	}
	meta, err := m.repository.AuthorizedMessageAttachment(ctx, account, entry, id)
	if err != nil {
		return meta, nil, err
	}
	data, err := m.objects.Read(ctx, meta.ObjectID)
	return meta, data, err
}
func (m *Mailbox) DraftAttachment(ctx context.Context, account, draft, id string) (domain.Attachment, []byte, error) {
	if err := validateTriple(account, draft, id); err != nil {
		return domain.Attachment{}, nil, err
	}
	meta, err := m.repository.AuthorizedDraftAttachment(ctx, account, draft, id)
	if err != nil {
		return meta, nil, err
	}
	data, err := m.objects.Read(ctx, meta.ObjectID)
	return meta, data, err
}

func (m *Mailbox) Categories(ctx context.Context, account string) ([]domain.Category, error) {
	if err := validateID(account); err != nil {
		return nil, err
	}
	return m.repository.Categories(ctx, account)
}
func (m *Mailbox) CreateCategory(ctx context.Context, account, name string) (domain.Category, error) {
	if err := validateID(account); err != nil {
		return domain.Category{}, err
	}
	name, err := validateCategory(name)
	if err != nil {
		return domain.Category{}, err
	}
	return m.repository.CreateCategory(ctx, account, name)
}
func (m *Mailbox) RenameCategory(ctx context.Context, account, id string, version int64, name string) (domain.Category, error) {
	if err := validatePair(account, id); err != nil {
		return domain.Category{}, err
	}
	if version < 1 {
		return domain.Category{}, &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	name, err := validateCategory(name)
	if err != nil {
		return domain.Category{}, err
	}
	return m.repository.RenameCategory(ctx, account, id, version, name)
}
func (m *Mailbox) DeleteCategory(ctx context.Context, account, id string, version int64) error {
	if err := validatePair(account, id); err != nil {
		return err
	}
	if version < 1 {
		return &domain.InvalidError{Code: "INVALID_VERSION"}
	}
	return m.repository.DeleteCategory(ctx, account, id, version)
}

func (m *Mailbox) validateDraft(input domain.DraftInput) (domain.DraftInput, error) {
	input.Subject = strings.TrimSpace(input.Subject)
	if len([]byte(input.Subject)) > 998 {
		return input, &domain.InvalidError{Code: "SUBJECT_TOO_LONG"}
	}
	if len([]byte(input.TextBody))+len([]byte(input.HTMLBody)) > maxMailboxBytes {
		return input, &domain.InvalidError{Code: "DRAFT_SIZE_EXCEEDED"}
	}
	var err error
	if input.To, err = addresses(input.To); err != nil {
		return input, err
	}
	if input.CC, err = addresses(input.CC); err != nil {
		return input, err
	}
	if input.BCC, err = addresses(input.BCC); err != nil {
		return input, err
	}
	if len(input.To)+len(input.CC)+len(input.BCC) > 10 {
		return input, &domain.InvalidError{Code: "RECIPIENT_LIMIT"}
	}
	if input.Mode == "" {
		input.Mode = domain.Compose
	}
	if !input.Mode.Valid() {
		return input, &domain.InvalidError{Code: "INVALID_DRAFT_MODE"}
	}
	if input.SourceContentID != nil {
		if err := validateID(*input.SourceContentID); err != nil {
			return input, err
		}
	}
	input.HTMLBody = m.sanitizer.Sanitize(input.HTMLBody)
	return input, nil
}
func addresses(values []string) ([]string, error) {
	result := []string{}
	seen := map[string]bool{}
	for _, value := range values {
		value = strings.ToLower(strings.TrimSpace(value))
		if !utf8.ValidString(value) || !mailboxAddress.MatchString(value) {
			return nil, &domain.InvalidError{Code: "INVALID_ADDRESS"}
		}
		if !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	return result, nil
}
func validateCategory(value string) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" || len([]rune(value)) > 40 {
		return "", &domain.InvalidError{Code: "INVALID_CATEGORY"}
	}
	return value, nil
}
func validateFileName(value string) (string, error) {
	value = strings.TrimSpace(value)
	if value == "" || value == "." || value == ".." || len([]rune(value)) > 255 || strings.ContainsAny(value, "/\\\r\n\x00") {
		return "", &domain.InvalidError{Code: "INVALID_FILE_NAME"}
	}
	return value, nil
}
func validatePair(a, b string) error {
	if err := validateID(a); err != nil {
		return err
	}
	return validateID(b)
}
func validateTriple(a, b, c string) error {
	if err := validatePair(a, b); err != nil {
		return err
	}
	return validateID(c)
}
func containsAddress(values []string, value string) bool {
	for _, candidate := range values {
		if strings.EqualFold(candidate, value) {
			return true
		}
	}
	return false
}
func prefix(subject, value string) string {
	if strings.HasPrefix(strings.ToLower(subject), strings.ToLower(value)) {
		return subject
	}
	return value + subject
}
func (m *Mailbox) String() string { return fmt.Sprintf("mailbox(%T)", m.repository) }
