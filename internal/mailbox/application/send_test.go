package application

import (
	"bytes"
	"net/mail"
	"testing"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
)

func TestBuildMIMEIncludesReplyThreadHeadersAndOmitsBCC(t *testing.T) {
	draft := domain.Draft{Subject: "回复", TextBody: "正文", To: []string{"bob@guihong.test"},
		BCC: []string{"carol@guihong.test"}, Mode: domain.Reply}
	raw, err := buildMIME("00000000-0000-0000-0000-000000000001", "alice@guihong.test", draft, nil, "<source@example.test>")
	if err != nil {
		t.Fatal(err)
	}
	message, err := mail.ReadMessage(bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if message.Header.Get("In-Reply-To") != "<source@example.test>" || message.Header.Get("References") != "<source@example.test>" {
		t.Fatalf("reply headers missing: %#v", message.Header)
	}
	if message.Header.Get("Bcc") != "" {
		t.Fatalf("BCC leaked into wire MIME: %q", message.Header.Get("Bcc"))
	}
}
