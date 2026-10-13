package infrastructure

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/NoctilumeDev/GuiHongMail/internal/mailbox/domain"
	"github.com/NoctilumeDev/GuiHongMail/internal/platform"
	"github.com/google/uuid"
)

type IdentityRepository struct {
	database *sql.DB
	witness  *platform.Witness
	writable func(context.Context) bool
}

func NewIdentityRepository(database *sql.DB, witness *platform.Witness, writable func(context.Context) bool) *IdentityRepository {
	return &IdentityRepository{database: database, witness: witness, writable: writable}
}

func (repository *IdentityRepository) Available(ctx context.Context) bool {
	return repository.writable(ctx)
}

func (repository *IdentityRepository) FailedLoginAttempt(ctx context.Context, bucket string, minute int64) (int, error) {
	if !repository.Available(ctx) {
		return 0, fmt.Errorf("service unavailable")
	}
	attempts := 0
	err := repository.witness.Write(ctx, fmt.Sprintf("login-budget|%s|%d", bucket, minute), func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, `INSERT INTO login_buckets(bucket_hash,minute_window,attempts) VALUES(?,?,1)
			ON DUPLICATE KEY UPDATE attempts=IF(minute_window=?,attempts+1,1),minute_window=?`, bucket, minute, minute, minute)
		if err != nil {
			return err
		}
		return tx.QueryRowContext(ctx, "SELECT attempts FROM login_buckets WHERE bucket_hash=?", bucket).Scan(&attempts)
	})
	return attempts, err
}

func (repository *IdentityRepository) ByAddress(ctx context.Context, address string) (*domain.Account, error) {
	return repository.account(ctx, "SELECT account_id,address,display_name,password_hash,enabled,auth_epoch,role FROM accounts WHERE address=?", address)
}

func (repository *IdentityRepository) ByID(ctx context.Context, id string) (*domain.Account, error) {
	return repository.account(ctx, "SELECT account_id,address,display_name,password_hash,enabled,auth_epoch,role FROM accounts WHERE account_id=?", id)
}

func (repository *IdentityRepository) account(ctx context.Context, query, value string) (*domain.Account, error) {
	var account domain.Account
	err := repository.database.QueryRowContext(ctx, query, value).Scan(&account.ID, &account.Address, &account.DisplayName,
		&account.PasswordHash, &account.Enabled, &account.Epoch, &account.Role)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return &account, err
}

func (repository *IdentityRepository) Authenticate(ctx context.Context, tokenHash string) (*domain.Principal, error) {
	if !repository.Available(ctx) {
		return nil, fmt.Errorf("service unavailable")
	}
	var principal domain.Principal
	err := repository.database.QueryRowContext(ctx, `SELECT a.account_id,a.address,a.display_name,a.role,s.token_hash,s.csrf_hash
		FROM sessions s JOIN accounts a ON a.account_id=s.account_id
		WHERE s.token_hash=? AND s.expires_at>NOW(6) AND a.enabled=1 AND s.auth_epoch=a.auth_epoch`, tokenHash).
		Scan(&principal.AccountID, &principal.Address, &principal.DisplayName, &principal.Role, &principal.SessionHash, &principal.CSRFHash)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	return &principal, err
}

func (repository *IdentityRepository) CreateSession(ctx context.Context, account domain.Account, tokenHash, csrfHash, oldHash string) error {
	if !repository.Available(ctx) {
		return fmt.Errorf("service unavailable")
	}
	return repository.witness.Write(ctx, "session-create|"+account.ID+"|"+tokenHash, func(tx *sql.Tx) error {
		var enabled bool
		var epoch int64
		if err := tx.QueryRowContext(ctx, "SELECT enabled,auth_epoch FROM accounts WHERE account_id=? FOR UPDATE", account.ID).Scan(&enabled, &epoch); err != nil {
			return err
		}
		if !enabled || epoch != account.Epoch {
			return fmt.Errorf("account changed")
		}
		if oldHash != "" {
			result, err := tx.ExecContext(ctx, "DELETE FROM sessions WHERE token_hash=? AND account_id=?", oldHash, account.ID)
			if err != nil {
				return err
			}
			count, err := result.RowsAffected()
			if err != nil || count != 1 {
				return fmt.Errorf("session already rotated")
			}
		}
		_, err := tx.ExecContext(ctx, `INSERT INTO sessions(token_hash,account_id,csrf_hash,auth_epoch,expires_at)
			VALUES(?,?,?,?,DATE_ADD(NOW(6),INTERVAL 30 MINUTE))`, tokenHash, account.ID, csrfHash, account.Epoch)
		return err
	})
}

func (repository *IdentityRepository) Logout(ctx context.Context, sessionHash string) error {
	return repository.witness.Write(ctx, "session-logout|"+sessionHash, func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, "DELETE FROM sessions WHERE token_hash=?", sessionHash)
		return err
	})
}

func (repository *IdentityRepository) Provision(ctx context.Context, address, passwordHash, displayName string) (string, error) {
	id := uuid.NewString()
	err := repository.witness.Write(ctx, "account-provision|"+id+"|"+platform.SHA256([]byte(address)), func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, "INSERT INTO accounts(account_id,address,password_hash,display_name) VALUES(?,?,?,?)",
			id, address, passwordHash, displayName)
		return err
	})
	return id, err
}

func (repository *IdentityRepository) SetEnabled(ctx context.Context, id string, enabled bool) error {
	if _, err := uuid.Parse(id); err != nil {
		return fmt.Errorf("account not found")
	}
	return repository.witness.Write(ctx, fmt.Sprintf("account-enable|%s|%t", id, enabled), func(tx *sql.Tx) error {
		result, err := tx.ExecContext(ctx, "UPDATE accounts SET enabled=?,auth_epoch=auth_epoch+1 WHERE account_id=?", enabled, id)
		if err != nil {
			return err
		}
		count, err := result.RowsAffected()
		if err != nil || count != 1 {
			return fmt.Errorf("account not found")
		}
		return nil
	})
}
