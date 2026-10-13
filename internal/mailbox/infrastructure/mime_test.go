package infrastructure

import (
	"errors"
	"strings"
	"testing"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
)

func TestMIMEParserKeepsRawHTMLInInertProjectionAndParsesAttachment(t *testing.T) {
	raw := []byte("From: Alice <alice@example.test>\r\nTo: Bob <bob@guihong.test>\r\nSubject: =?UTF-8?B?5rWL6K+V?=\r\nContent-Type: multipart/mixed; boundary=x\r\n\r\n--x\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Hello<script>alert(1)</script></p>\r\n--x\r\nContent-Type: text/plain\r\nContent-Disposition: attachment; filename=note.txt\r\n\r\nevidence\r\n--x--\r\n")
	message, err := (MIMEParser{}).Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if message.Subject != "测试" || message.From.Address != "alice@example.test" {
		t.Fatalf("unexpected headers: %#v", message)
	}
	if strings.Contains(message.SafeHTML, "<script>") || !strings.Contains(message.SafeHTML, "&lt;script&gt;") {
		t.Fatalf("active HTML survived: %s", message.SafeHTML)
	}
	if len(message.Attachments) != 1 || message.Attachments[0].FileName != "note.txt" || string(message.Attachments[0].Bytes) != "evidence" {
		t.Fatalf("attachment mismatch: %#v", message.Attachments)
	}
}

func TestMIMEParserRejectsTraversalAndOversizedHeaders(t *testing.T) {
	cases := map[string][]byte{
		"subject": []byte("From: a@example.test\r\nSubject: " + strings.Repeat("x", 999) + "\r\n\r\nbody"),
		"path":    []byte("From: a@example.test\r\nContent-Type: text/plain\r\nContent-Disposition: attachment; filename=\"../x\"\r\n\r\nbody"),
	}
	for name, raw := range cases {
		_, err := (MIMEParser{}).Parse(raw)
		var invalid *domain.InvalidError
		if !errors.As(err, &invalid) {
			t.Fatalf("%s: expected bounded rejection, got %v", name, err)
		}
	}
}
