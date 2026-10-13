package application

import (
	"errors"
	"testing"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
)

type testSanitizer struct{}

func (testSanitizer) Sanitize(value string) string { return "safe:" + value }

func TestDraftValidationNormalizesAndBoundsRecipients(t *testing.T) {
	mailbox := &Mailbox{sanitizer: testSanitizer{}}
	input, err := mailbox.validateDraft(domain.DraftInput{Subject: " subject ", To: []string{" ALICE@example.test ", "alice@example.test"}, CC: []string{}, BCC: []string{}})
	if err != nil {
		t.Fatal(err)
	}
	if input.Subject != "subject" || len(input.To) != 1 || input.To[0] != "alice@example.test" || input.Mode != domain.Compose || input.HTMLBody != "safe:" {
		t.Fatalf("unexpected normalized draft: %#v", input)
	}
	_, err = mailbox.validateDraft(domain.DraftInput{To: []string{"not-an-address"}})
	var invalid *domain.InvalidError
	if !errors.As(err, &invalid) || invalid.Code != "INVALID_ADDRESS" {
		t.Fatalf("wrong error: %v", err)
	}
}

func TestFileNameRejectsPathAndControlCharacters(t *testing.T) {
	for _, value := range []string{"../secret", "dir/file", "line\nbreak", "."} {
		if _, err := validateFileName(value); err == nil {
			t.Fatalf("accepted %q", value)
		}
	}
	if value, err := validateFileName(" report.txt "); err != nil || value != "report.txt" {
		t.Fatalf("valid name rejected: %q %v", value, err)
	}
}
