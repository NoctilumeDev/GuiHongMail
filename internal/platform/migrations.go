package platform

import "fmt"

type Migration struct {
	Version    int
	Name       string
	Statements []string
}

func Migrations(role string) ([]Migration, error) {
	foundation := Migration{Version: 1, Name: "foundation", Statements: []string{
		`CREATE TABLE foundation_meta (singleton TINYINT PRIMARY KEY, generation CHAR(36) NOT NULL, last_committed_seq BIGINT NOT NULL, CONSTRAINT single_generation CHECK(singleton=1))`,
		`CREATE TABLE tx_receipts (tx_id CHAR(36) PRIMARY KEY, sequence_no BIGINT NOT NULL UNIQUE, payload_sha256 CHAR(64) NOT NULL)`,
		`CREATE TABLE stored_objects (object_id CHAR(36) PRIMARY KEY, object_key VARCHAR(200) NOT NULL UNIQUE, authority_key VARCHAR(128) NOT NULL, sha256 CHAR(64) NOT NULL, byte_size BIGINT NOT NULL, lifecycle VARCHAR(24) NOT NULL, in_flight INT NOT NULL DEFAULT 0, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), CONSTRAINT nonnegative_size CHECK(byte_size>=0), CONSTRAINT nonnegative_inflight CHECK(in_flight>=0))`,
		`CREATE TABLE object_refs (ref_kind VARCHAR(32) NOT NULL, ref_id VARCHAR(64) NOT NULL, object_id CHAR(36) NOT NULL, PRIMARY KEY(ref_kind,ref_id,object_id), FOREIGN KEY(object_id) REFERENCES stored_objects(object_id))`,
	}}
	result := []Migration{foundation}
	switch role {
	case "mailbox":
		result = append(result, Migration{Version: 2, Name: "identity", Statements: []string{
			`CREATE TABLE accounts (account_id CHAR(36) PRIMARY KEY, address VARCHAR(254) NOT NULL UNIQUE, password_hash VARCHAR(100) NOT NULL, display_name VARCHAR(80) NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE, auth_epoch BIGINT NOT NULL DEFAULT 1, role VARCHAR(16) NOT NULL DEFAULT 'USER', created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6))`,
			`CREATE TABLE sessions (token_hash CHAR(64) PRIMARY KEY, account_id CHAR(36) NOT NULL, csrf_hash CHAR(64) NOT NULL, auth_epoch BIGINT NOT NULL, expires_at TIMESTAMP(6) NOT NULL, FOREIGN KEY(account_id) REFERENCES accounts(account_id))`,
			`CREATE TABLE login_buckets (bucket_hash CHAR(64) PRIMARY KEY, minute_window BIGINT NOT NULL, attempts INT NOT NULL)`,
		}})
	case "ingress", "delivery":
	default:
		return nil, fmt.Errorf("unknown migration role")
	}
	return result, nil
}

func migrationDigest(migration Migration) string {
	value := fmt.Sprintf("%d|%s", migration.Version, migration.Name)
	for _, statement := range migration.Statements {
		value += "|" + statement
	}
	return SHA256([]byte(value))
}
