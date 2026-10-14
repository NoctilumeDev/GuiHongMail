package application

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"mime"
	"mime/multipart"
	"mime/quotedprintable"
	"net/textproto"
	"regexp"
	"strings"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
	"github.com/google/uuid"
)

const sendTopic = "guihong_mail_send_v1"

var requestKeyPattern = regexp.MustCompile(`^[\x21-\x7e]{1,128}$`)

type Sender struct {
	mailbox domain.MailboxRepository
	sends   domain.SendRepository
	parser  MessageParser
	objects *platform.ObjectRepository
}

func NewSender(mailbox domain.MailboxRepository, sends domain.SendRepository, parser MessageParser, objects *platform.ObjectRepository) *Sender {
	return &Sender{mailbox: mailbox, sends: sends, parser: parser, objects: objects}
}

type sendEvent struct {
	Version         int                        `json:"version"`
	SourceService   string                     `json:"sourceService"`
	IntentID        string                     `json:"intentId"`
	DispatchScopeID string                     `json:"dispatchScopeId"`
	Sender          string                     `json:"sender"`
	Envelope        []domain.EnvelopeRecipient `json:"envelope"`
	RawSHA256       string                     `json:"rawSha256"`
	RawSize         int64                      `json:"rawSize"`
	RawURL          string                     `json:"rawUrl"`
}

func (s *Sender) Submit(ctx context.Context, account, draftID string, version int64, key string) (domain.SendIntent, error) {
	if validateID(account) != nil || validateID(draftID) != nil || version < 1 || !requestKeyPattern.MatchString(key) {
		return domain.SendIntent{}, &domain.InvalidError{Code: "INVALID_SEND_REQUEST"}
	}
	if existing, err := s.sends.ExistingSend(ctx, account, key); err != nil {
		return domain.SendIntent{}, err
	} else if existing != nil {
		if existing.DraftID != draftID || existing.DraftVersion != version {
			return domain.SendIntent{}, domain.ErrIdempotencyConflict
		}
		return *existing, nil
	}
	draft, err := s.mailbox.Draft(ctx, account, draftID)
	if err != nil {
		return domain.SendIntent{}, err
	}
	if draft.Version != version {
		return domain.SendIntent{}, &domain.VersionConflictError{Current: draft.Version}
	}
	if len(draft.To)+len(draft.CC)+len(draft.BCC) == 0 {
		return domain.SendIntent{}, &domain.InvalidError{Code: "RECIPIENT_REQUIRED"}
	}
	sender, err := s.mailbox.AccountAddress(ctx, account)
	if err != nil {
		return domain.SendIntent{}, err
	}
	files := make([][]byte, len(draft.Attachments))
	for index, attachment := range draft.Attachments {
		files[index], err = s.objects.Read(ctx, attachment.ObjectID)
		if err != nil {
			return domain.SendIntent{}, err
		}
		if int64(len(files[index])) != attachment.Size || platform.SHA256(files[index]) != attachment.SHA256 {
			return domain.SendIntent{}, errors.New("attachment object mismatch")
		}
	}
	intentID, scopeID, contentID := uuid.NewString(), uuid.NewString(), uuid.NewString()
	replyReference := ""
	if draft.SourceContentID != nil && (draft.Mode == domain.Reply || draft.Mode == domain.ReplyAll) {
		replyReference, err = s.mailbox.ReplyReference(ctx, account, *draft.SourceContentID)
		if err != nil {
			return domain.SendIntent{}, err
		}
	}
	raw, err := buildMIME(intentID, sender, draft, files, replyReference)
	if err != nil || len(raw) > maxMailboxBytes {
		return domain.SendIntent{}, &domain.InvalidError{Code: "MIME_SIZE_EXCEEDED"}
	}
	parsed, err := s.parser.Parse(raw)
	if err != nil {
		return domain.SendIntent{}, err
	}
	for ordinal, address := range draft.BCC {
		parsed.Recipients = append(parsed.Recipients, domain.Recipient{Kind: "BCC", Ordinal: ordinal, Address: address})
	}
	envelope := make([]domain.EnvelopeRecipient, 0, len(draft.To)+len(draft.CC)+len(draft.BCC))
	for _, pair := range []struct {
		kind   string
		values []string
	}{{"TO", draft.To}, {"CC", draft.CC}, {"BCC", draft.BCC}} {
		for _, address := range pair.values {
			envelope = append(envelope, domain.EnvelopeRecipient{Kind: pair.kind, Address: address})
		}
	}
	payloadBytes, _ := json.Marshal(struct {
		DraftID string                     `json:"draftId"`
		Version int64                      `json:"version"`
		Raw     string                     `json:"rawSha256"`
		From    string                     `json:"from"`
		To      []domain.EnvelopeRecipient `json:"envelope"`
	}{draftID, version, platform.SHA256(raw), sender, envelope})
	payloadDigest := platform.SHA256(payloadBytes)
	blob, err := s.objects.Stage(ctx, uuid.NewString(), "send-raw:"+intentID, raw)
	if err != nil {
		return domain.SendIntent{}, err
	}
	if blob, err = s.objects.Reference(ctx, blob.ID, "SEND_RAW", intentID); err != nil {
		return domain.SendIntent{}, err
	}
	event := sendEvent{Version: 1, SourceService: "mailbox", IntentID: intentID, DispatchScopeID: scopeID,
		Sender: sender, Envelope: envelope, RawSHA256: blob.SHA256, RawSize: blob.Size,
		RawURL: "http://127.0.0.1:18080/internal/send-intents/" + intentID + "/raw"}
	eventBytes, _ := json.Marshal(event)
	messageFiles := make([]domain.StoredAttachment, len(draft.Attachments))
	for index, attachment := range draft.Attachments {
		messageFiles[index] = domain.StoredAttachment{ID: uuid.NewString(), ObjectID: attachment.ObjectID, FileName: attachment.FileName,
			MediaType: attachment.MediaType, SHA256: attachment.SHA256, Size: attachment.Size}
	}
	command := domain.SendFreeze{IntentID: intentID, AccountID: account, Draft: draft, RequestKey: key,
		PayloadSHA256: payloadDigest, DispatchScopeID: scopeID, ContentID: contentID, RawObjectID: blob.ID,
		RawSHA256: blob.SHA256, RawSize: blob.Size, SenderAddress: sender, Envelope: envelope, Parsed: parsed,
		MessageFiles: messageFiles, OutboxEventID: uuid.NewString(), OutboxPayload: eventBytes}
	result, err := s.sends.FreezeSend(ctx, command)
	if err != nil {
		var unknown *platform.CommitUnknownError
		if !errors.As(err, &unknown) {
			_ = s.objects.Dereference(ctx, blob.ID, "SEND_RAW", intentID)
		}
		return domain.SendIntent{}, err
	}
	return result, nil
}

func (s *Sender) Intent(ctx context.Context, account, id string) (domain.SendIntent, error) {
	if validateID(account) != nil || validateID(id) != nil {
		return domain.SendIntent{}, &domain.InvalidError{Code: "INVALID_ID"}
	}
	return s.sends.Send(ctx, account, id)
}

func (s *Sender) Raw(ctx context.Context, id string) ([]byte, string, error) {
	if validateID(id) != nil {
		return nil, "", &domain.InvalidError{Code: "INVALID_ID"}
	}
	object, digest, size, err := s.sends.SendRaw(ctx, id)
	if err != nil {
		return nil, "", err
	}
	data, err := s.objects.Read(ctx, object)
	if err != nil {
		return nil, "", err
	}
	if int64(len(data)) != size || platform.SHA256(data) != digest {
		return nil, "", errors.New("send raw mismatch")
	}
	return data, digest, nil
}

func buildMIME(intent, sender string, draft domain.Draft, files [][]byte, replyReference string) ([]byte, error) {
	var output bytes.Buffer
	writeHeader := func(name, value string) { fmt.Fprintf(&output, "%s: %s\r\n", name, value) }
	writeHeader("From", sender)
	if len(draft.To) > 0 {
		writeHeader("To", strings.Join(draft.To, ", "))
	}
	if len(draft.CC) > 0 {
		writeHeader("Cc", strings.Join(draft.CC, ", "))
	}
	writeHeader("Subject", mime.QEncoding.Encode("UTF-8", draft.Subject))
	writeHeader("Date", time.Now().UTC().Format(time.RFC1123Z))
	writeHeader("Message-ID", "<"+intent+"@guihong.test>")
	if replyReference != "" {
		writeHeader("In-Reply-To", replyReference)
		writeHeader("References", replyReference)
	}
	writeHeader("MIME-Version", "1.0")
	mixed := multipart.NewWriter(&output)
	writeHeader("Content-Type", `multipart/mixed; boundary="`+mixed.Boundary()+`"`)
	output.WriteString("\r\n")
	alternativeHeader := textproto.MIMEHeader{}
	alternativeBoundary := "guihong-alt-" + strings.ReplaceAll(intent, "-", "")
	alternativeHeader.Set("Content-Type", `multipart/alternative; boundary="`+alternativeBoundary+`"`)
	part, err := mixed.CreatePart(alternativeHeader)
	if err != nil {
		return nil, err
	}
	alternative := multipart.NewWriter(part)
	if err := alternative.SetBoundary(alternativeBoundary); err != nil {
		return nil, err
	}
	for _, body := range []struct{ media, value string }{{"text/plain", draft.TextBody}, {"text/html", draft.HTMLBody}} {
		if body.media == "text/html" && body.value == "" {
			continue
		}
		header := textproto.MIMEHeader{}
		header.Set("Content-Type", body.media+`; charset="utf-8"`)
		header.Set("Content-Transfer-Encoding", "quoted-printable")
		piece, err := alternative.CreatePart(header)
		if err != nil {
			return nil, err
		}
		encoder := quotedprintable.NewWriter(piece)
		if _, err := encoder.Write([]byte(body.value)); err != nil {
			return nil, err
		}
		if err := encoder.Close(); err != nil {
			return nil, err
		}
	}
	if err := alternative.Close(); err != nil {
		return nil, err
	}
	for index, attachment := range draft.Attachments {
		header := textproto.MIMEHeader{}
		header.Set("Content-Type", attachment.MediaType)
		header.Set("Content-Transfer-Encoding", "base64")
		header.Set("Content-Disposition", mime.FormatMediaType("attachment", map[string]string{"filename": attachment.FileName}))
		piece, err := mixed.CreatePart(header)
		if err != nil {
			return nil, err
		}
		encoded := base64.StdEncoding.EncodeToString(files[index])
		for len(encoded) > 76 {
			fmt.Fprint(piece, encoded[:76]+"\r\n")
			encoded = encoded[76:]
		}
		fmt.Fprint(piece, encoded+"\r\n")
	}
	if err := mixed.Close(); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}
