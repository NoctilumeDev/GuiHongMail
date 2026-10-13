package application

import (
	"context"
	"errors"
	"testing"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"golang.org/x/crypto/bcrypt"
)

type identityMemory struct {
	account        *domain.Account
	attempts       int
	sessionToken   string
	sessionCSRF    string
	sessionOldHash string
}

func (memory *identityMemory) Available(context.Context) bool { return true }
func (memory *identityMemory) FailedLoginAttempt(context.Context, string, int64) (int, error) {
	memory.attempts++
	return memory.attempts, nil
}
func (memory *identityMemory) ByAddress(_ context.Context, address string) (*domain.Account, error) {
	if memory.account != nil && memory.account.Address == address {
		copy := *memory.account
		return &copy, nil
	}
	return nil, nil
}
func (memory *identityMemory) ByID(context.Context, string) (*domain.Account, error) {
	if memory.account == nil {
		return nil, nil
	}
	copy := *memory.account
	return &copy, nil
}
func (memory *identityMemory) Authenticate(context.Context, string) (*domain.Principal, error) {
	return nil, nil
}
func (memory *identityMemory) CreateSession(_ context.Context, _ domain.Account, token, csrf, old string) error {
	memory.sessionToken, memory.sessionCSRF, memory.sessionOldHash = token, csrf, old
	return nil
}
func (memory *identityMemory) Logout(context.Context, string) error { return nil }
func (memory *identityMemory) Provision(context.Context, string, string, string) (string, error) {
	return "new", nil
}
func (memory *identityMemory) SetEnabled(context.Context, string, bool) error { return nil }

func TestLoginUsesUniformFailureAndCreatesDistinctSecrets(t *testing.T) {
	hash, err := bcrypt.GenerateFromPassword([]byte("correct horse battery"), 10)
	if err != nil {
		t.Fatal(err)
	}
	memory := &identityMemory{account: &domain.Account{ID: "account", Address: "alice@guihong.test",
		DisplayName: "Alice", PasswordHash: string(hash), Enabled: true, Epoch: 1, Role: "USER"}}
	identity, err := NewIdentity(memory)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := identity.Login(context.Background(), "missing@guihong.test", "wrong password", "127.0.0.1"); !errors.Is(err, ErrAuthentication) {
		t.Fatalf("missing account failure = %v", err)
	}
	if _, err := identity.Login(context.Background(), "alice@guihong.test", "wrong password", "127.0.0.1"); !errors.Is(err, ErrAuthentication) {
		t.Fatalf("wrong password failure = %v", err)
	}
	session, err := identity.Login(context.Background(), "Alice@GuiHong.Test", "correct horse battery", "127.0.0.1")
	if err != nil {
		t.Fatal(err)
	}
	if len(session.Token) != 43 || len(session.CSRF) != 43 || session.Token == session.CSRF {
		t.Fatalf("session secrets are not independent 256-bit tokens")
	}
	if memory.sessionToken == "" || memory.sessionCSRF == "" || memory.sessionToken == memory.sessionCSRF {
		t.Fatal("repository did not receive separate token and CSRF digests")
	}
	if memory.sessionToken == session.Token || memory.sessionCSRF == session.CSRF {
		t.Fatal("repository received raw session material")
	}
}

func TestLoginRateLimitStartsAfterFiveFailures(t *testing.T) {
	memory := &identityMemory{}
	identity, err := NewIdentity(memory)
	if err != nil {
		t.Fatal(err)
	}
	for attempt := 1; attempt <= 5; attempt++ {
		if _, err := identity.Login(context.Background(), "nobody@guihong.test", "wrong", "127.0.0.1"); !errors.Is(err, ErrAuthentication) {
			t.Fatalf("attempt %d = %v", attempt, err)
		}
	}
	if _, err := identity.Login(context.Background(), "nobody@guihong.test", "wrong", "127.0.0.1"); !errors.Is(err, ErrRateLimited) {
		t.Fatalf("sixth attempt = %v", err)
	}
}
