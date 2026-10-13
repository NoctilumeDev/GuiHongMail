CREATE TABLE accounts (
 account_id CHAR(36) PRIMARY KEY, address VARCHAR(254) NOT NULL UNIQUE,
 password_hash VARCHAR(100) NOT NULL, display_name VARCHAR(80) NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT TRUE, auth_epoch BIGINT NOT NULL DEFAULT 1,
 role VARCHAR(16) NOT NULL DEFAULT 'USER', created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
);
CREATE TABLE sessions (
 token_hash CHAR(64) PRIMARY KEY, account_id CHAR(36) NOT NULL,
 csrf_hash CHAR(64) NOT NULL, auth_epoch BIGINT NOT NULL, expires_at TIMESTAMP(6) NOT NULL,
 FOREIGN KEY(account_id) REFERENCES accounts(account_id)
);
CREATE TABLE login_buckets (
 bucket_hash CHAR(64) PRIMARY KEY, minute_window BIGINT NOT NULL, attempts INT NOT NULL
);
