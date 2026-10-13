package infrastructure

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"html"
	"io"
	"mime"
	"mime/multipart"
	"mime/quotedprintable"
	"net/mail"
	"net/textproto"
	"path/filepath"
	"strings"
	"time"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
)

const maxMIMEBytes = 5 * 1024 * 1024

type MIMEParser struct{}
type mimeState struct {
	parts       int
	decoded     int
	plain       []string
	html        []string
	attachments []domain.ParsedAttachment
}

func (MIMEParser) Parse(raw []byte) (domain.ParsedMessage, error) {
	if len(raw) == 0 || len(raw) > maxMIMEBytes {
		return domain.ParsedMessage{}, invalid("MIME_SIZE_EXCEEDED")
	}
	message, err := mail.ReadMessage(bytes.NewReader(raw))
	if err != nil {
		return domain.ParsedMessage{}, invalid("MIME_MALFORMED")
	}
	from, err := mail.ParseAddress(message.Header.Get("From"))
	if err != nil || from.Address == "" {
		return domain.ParsedMessage{}, invalid("MIME_FROM_REQUIRED")
	}
	state := &mimeState{}
	if err := walkMIME(textproto.MIMEHeader(message.Header), message.Body, 0, state); err != nil {
		return domain.ParsedMessage{}, err
	}
	recipients := []domain.Recipient{}
	for _, item := range []struct{ header, kind string }{{"To", "TO"}, {"Cc", "CC"}, {"Bcc", "BCC"}} {
		values, parseErr := mail.ParseAddressList(message.Header.Get(item.header))
		if parseErr != nil && message.Header.Get(item.header) != "" {
			return domain.ParsedMessage{}, invalid("MIME_RECIPIENT_INVALID")
		}
		for index, value := range values {
			name := cleanHeader(value.Name, 200)
			var namePointer *string
			if name != "" {
				namePointer = &name
			}
			recipients = append(recipients, domain.Recipient{Kind: item.kind, Ordinal: index, Address: strings.ToLower(value.Address), Name: namePointer})
		}
	}
	subject, err := decodeHeader(message.Header.Get("Subject"), 998)
	if err != nil {
		return domain.ParsedMessage{}, err
	}
	messageID := cleanHeader(message.Header.Get("Message-ID"), 998)
	var sent *time.Time
	if parsed, parseErr := message.Header.Date(); parseErr == nil {
		value := parsed.UTC()
		sent = &value
	}
	text := strings.Join(state.plain, "\n")
	safe := ""
	if len(state.html) > 0 {
		safe = safeProjection(strings.Join(state.html, "\n"))
		if strings.TrimSpace(text) == "" {
			text = strings.Join(state.html, " ")
		}
	}
	return domain.ParsedMessage{MessageID: messageID, From: domain.Address{Address: strings.ToLower(from.Address), Name: cleanHeader(from.Name, 200)}, Subject: subject, TextBody: text, SafeHTML: safe, SentAt: sent, Recipients: recipients, Attachments: state.attachments}, nil
}

func walkMIME(header textproto.MIMEHeader, body io.Reader, depth int, state *mimeState) error {
	state.parts++
	if depth > 8 || state.parts > 20 {
		return invalid("MIME_PART_LIMIT")
	}
	media, params, err := mime.ParseMediaType(header.Get("Content-Type"))
	if err != nil || media == "" {
		media = "text/plain"
	}
	decoded := decodeTransfer(header.Get("Content-Transfer-Encoding"), body)
	disposition, dparams, _ := mime.ParseMediaType(header.Get("Content-Disposition"))
	fileName := dparams["filename"]
	if fileName == "" {
		fileName = params["name"]
	}
	if strings.EqualFold(disposition, "attachment") || fileName != "" {
		data, err := readBounded(decoded, maxMIMEBytes-state.decoded)
		if err != nil {
			return err
		}
		state.decoded += len(data)
		name, err := safeFileName(fileName, len(state.attachments))
		if err != nil {
			return err
		}
		state.attachments = append(state.attachments, domain.ParsedAttachment{FileName: name, MediaType: strings.ToLower(media), Bytes: data, SHA256: platform.SHA256(data)})
		return nil
	}
	if strings.HasPrefix(strings.ToLower(media), "multipart/") {
		boundary := params["boundary"]
		if boundary == "" {
			return invalid("MIME_MALFORMED")
		}
		reader := multipart.NewReader(decoded, boundary)
		for {
			part, err := reader.NextPart()
			if err == io.EOF {
				break
			}
			if err != nil {
				return invalid("MIME_MALFORMED")
			}
			if err := walkMIME(part.Header, part, depth+1, state); err != nil {
				return err
			}
		}
		return nil
	}
	data, err := readBounded(decoded, maxMIMEBytes-state.decoded)
	if err != nil {
		return err
	}
	state.decoded += len(data)
	switch strings.ToLower(media) {
	case "text/plain":
		state.plain = append(state.plain, string(data))
	case "text/html":
		state.html = append(state.html, string(data))
	}
	return nil
}
func decodeTransfer(encoding string, reader io.Reader) io.Reader {
	switch strings.ToLower(strings.TrimSpace(encoding)) {
	case "base64":
		return base64.NewDecoder(base64.StdEncoding, reader)
	case "quoted-printable":
		return quotedprintable.NewReader(reader)
	default:
		return reader
	}
}
func readBounded(reader io.Reader, remaining int) ([]byte, error) {
	if remaining < 0 {
		return nil, invalid("MIME_DECODED_SIZE_EXCEEDED")
	}
	data, err := io.ReadAll(io.LimitReader(reader, int64(remaining+1)))
	if err != nil {
		return nil, invalid("MIME_MALFORMED")
	}
	if len(data) > remaining {
		return nil, invalid("MIME_DECODED_SIZE_EXCEEDED")
	}
	return data, nil
}
func decodeHeader(value string, max int) (string, error) {
	decoded, err := new(mime.WordDecoder).DecodeHeader(value)
	if err != nil {
		return "", invalid("MIME_MALFORMED")
	}
	clean := strings.TrimSpace(strings.ReplaceAll(strings.ReplaceAll(decoded, "\r", ""), "\n", ""))
	if len([]byte(clean)) > max {
		return "", invalid("MIME_HEADER_LIMIT")
	}
	return clean, nil
}
func cleanHeader(value string, max int) string {
	value = strings.TrimSpace(strings.ReplaceAll(strings.ReplaceAll(value, "\r", ""), "\n", ""))
	r := []rune(value)
	if len(r) > max {
		return string(r[:max])
	}
	return value
}
func safeFileName(value string, index int) (string, error) {
	if value == "" {
		value = fmt.Sprintf("attachment-%d", index)
	}
	decoded, err := new(mime.WordDecoder).DecodeHeader(value)
	if err != nil {
		return "", invalid("MIME_FILE_NAME_INVALID")
	}
	decoded = strings.TrimSpace(decoded)
	if decoded == "" || decoded == "." || decoded == ".." || filepath.Base(decoded) != decoded || strings.ContainsAny(decoded, "\r\n\x00") || len([]rune(decoded)) > 255 {
		return "", invalid("MIME_FILE_NAME_INVALID")
	}
	return decoded, nil
}

// safeProjection preserves the original bytes as readable text without granting
// active HTML any execution, navigation, network, style, or form capability.
func safeProjection(value string) string {
	if strings.TrimSpace(value) == "" {
		return ""
	}
	return "<pre>" + html.EscapeString(value) + "</pre>"
}

type ConservativeHTML struct{}

func (ConservativeHTML) Sanitize(value string) string { return safeProjection(value) }
