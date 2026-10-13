package application

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
	"golang.org/x/crypto/bcrypt"
)

var accountAddressPattern = regexp.MustCompile(`^[a-z0-9._-]{1,64}@guihong\.test$`)

var (
	ErrAuthentication = errors.New("AUTHENTICATION_FAILED")
	ErrRateLimited    = errors.New("RATE_LIMITED")
	ErrUnavailable    = errors.New("SERVICE_UNAVAILABLE")
	ErrInvalidAccount = errors.New("INVALID_ACCOUNT")
)

type Session struct {
	Token     string
	CSRF      string
	Principal domain.Principal
}

type Identity struct {
	repository domain.IdentityRepository
	dummyHash  string
}

func NewIdentity(repository domain.IdentityRepository) (*Identity, error) {
	dummy, err := bcrypt.GenerateFromPassword([]byte("synthetic-account-does-not-exist"), 10)
	if err != nil {
		return nil, err
	}
	return &Identity{repository: repository, dummyHash: string(dummy)}, nil
}

func (identity *Identity) Login(ctx context.Context, address, password, client string) (Session, error) {
	if !identity.repository.Available(ctx) {
		return Session{}, ErrUnavailable
	}
	if address == "" || len(address) > 254 || password == "" || len([]byte(password)) > 72 || !utf8.ValidString(password) {
		return Session{}, ErrAuthentication
	}
	normalized := strings.ToLower(address)
	account, lookupError := identity.repository.ByAddress(ctx, normalized)
	if lookupError != nil {
		return Session{}, ErrUnavailable
	}
	hash := identity.dummyHash
	if account != nil {
		hash = account.PasswordHash
	}
	matches := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
	if account == nil || !matches || !account.Enabled {
		attempts, err := identity.repository.FailedLoginAttempt(ctx, platform.SHA256([]byte(client+"|"+normalized)), time.Now().Unix()/60)
		if err != nil {
			return Session{}, ErrUnavailable
		}
		if attempts > 5 {
			return Session{}, ErrRateLimited
		}
		return Session{}, ErrAuthentication
	}
	return identity.createSession(ctx, *account, "")
}

func (identity *Identity) Authenticate(ctx context.Context, token string) (*domain.Principal, error) {
	if !identity.repository.Available(ctx) {
		return nil, ErrUnavailable
	}
	if len(token) != 43 {
		return nil, nil
	}
	for _, character := range token {
		if !(character >= 'a' && character <= 'z') && !(character >= 'A' && character <= 'Z') &&
			!(character >= '0' && character <= '9') && character != '_' && character != '-' {
			return nil, nil
		}
	}
	return identity.repository.Authenticate(ctx, platform.SHA256([]byte(token)))
}

func (identity *Identity) Refresh(ctx context.Context, principal domain.Principal) (Session, error) {
	if !identity.repository.Available(ctx) {
		return Session{}, ErrUnavailable
	}
	account, err := identity.repository.ByID(ctx, principal.AccountID)
	if err != nil || account == nil || !account.Enabled {
		return Session{}, ErrUnavailable
	}
	return identity.createSession(ctx, *account, principal.SessionHash)
}

func (identity *Identity) Logout(ctx context.Context, principal domain.Principal) error {
	if !identity.repository.Available(ctx) {
		return ErrUnavailable
	}
	return identity.repository.Logout(ctx, principal.SessionHash)
}

func (identity *Identity) Provision(ctx context.Context, address, password, displayName string) (string, error) {
	if !identity.repository.Available(ctx) {
		return "", ErrUnavailable
	}
	if !accountAddressPattern.MatchString(address) || len(password) < 12 || len([]byte(password)) > 72 ||
		displayName == "" || len([]rune(displayName)) > 80 {
		return "", ErrInvalidAccount
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), 10)
	if err != nil {
		return "", err
	}
	return identity.repository.Provision(ctx, address, string(hash), displayName)
}

func (identity *Identity) SetEnabled(ctx context.Context, id string, enabled bool) error {
	if !identity.repository.Available(ctx) {
		return ErrUnavailable
	}
	return identity.repository.SetEnabled(ctx, id, enabled)
}

func (identity *Identity) createSession(ctx context.Context, account domain.Account, oldHash string) (Session, error) {
	token, err := randomToken()
	if err != nil {
		return Session{}, err
	}
	csrf, err := randomToken()
	if err != nil {
		return Session{}, err
	}
	tokenHash := platform.SHA256([]byte(token))
	csrfHash := platform.SHA256([]byte(csrf))
	if err := identity.repository.CreateSession(ctx, account, tokenHash, csrfHash, oldHash); err != nil {
		return Session{}, fmt.Errorf("create session: %w", err)
	}
	return Session{Token: token, CSRF: csrf, Principal: domain.Principal{
		AccountID: account.ID, Address: account.Address, DisplayName: account.DisplayName, Role: account.Role,
		SessionHash: tokenHash, CSRFHash: csrfHash,
	}}, nil
}

func randomToken() (string, error) {
	buffer := make([]byte, 32)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buffer), nil
}
