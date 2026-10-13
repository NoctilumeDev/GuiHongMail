package domain

import "context"

type Account struct {
	ID           string
	Address      string
	DisplayName  string
	PasswordHash string
	Enabled      bool
	Epoch        int64
	Role         string
}

type Principal struct {
	AccountID   string
	Address     string
	DisplayName string
	Role        string
	SessionHash string
	CSRFHash    string
}

type IdentityRepository interface {
	Available(context.Context) bool
	FailedLoginAttempt(context.Context, string, int64) (int, error)
	ByAddress(context.Context, string) (*Account, error)
	ByID(context.Context, string) (*Account, error)
	Authenticate(context.Context, string) (*Principal, error)
	CreateSession(context.Context, Account, string, string, string) error
	Logout(context.Context, string) error
	Provision(context.Context, string, string, string) (string, error)
	SetEnabled(context.Context, string, bool) error
}
