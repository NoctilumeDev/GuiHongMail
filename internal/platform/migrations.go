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
		result = append(result, Migration{Version: 3, Name: "mailbox_core", Statements: []string{
			`CREATE TABLE message_contents (content_id CHAR(36) PRIMARY KEY, raw_object_id CHAR(36) NOT NULL, raw_sha256 CHAR(64) NOT NULL, raw_size BIGINT NOT NULL, message_id VARCHAR(998), from_address VARCHAR(254) NOT NULL, from_name VARCHAR(200), subject VARCHAR(998) NOT NULL, text_body MEDIUMTEXT NOT NULL, safe_html MEDIUMTEXT NOT NULL, sent_at TIMESTAMP(6), created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), UNIQUE(raw_sha256,raw_size), FOREIGN KEY(raw_object_id) REFERENCES stored_objects(object_id), CONSTRAINT message_raw_size CHECK(raw_size BETWEEN 1 AND 5242880))`,
			`CREATE TABLE message_recipients (content_id CHAR(36) NOT NULL, recipient_kind VARCHAR(3) NOT NULL, ordinal_no INT NOT NULL, address VARCHAR(254) NOT NULL, display_name VARCHAR(200), PRIMARY KEY(content_id,recipient_kind,ordinal_no), FOREIGN KEY(content_id) REFERENCES message_contents(content_id), CONSTRAINT recipient_kind_known CHECK(recipient_kind IN('TO','CC','BCC')))`,
			`CREATE TABLE message_attachments (attachment_id CHAR(36) PRIMARY KEY, content_id CHAR(36) NOT NULL, object_id CHAR(36) NOT NULL, ordinal_no INT NOT NULL, file_name VARCHAR(255) NOT NULL, media_type VARCHAR(120) NOT NULL, sha256 CHAR(64) NOT NULL, byte_size BIGINT NOT NULL, UNIQUE(content_id,ordinal_no), FOREIGN KEY(content_id) REFERENCES message_contents(content_id), FOREIGN KEY(object_id) REFERENCES stored_objects(object_id), CONSTRAINT message_attachment_size CHECK(byte_size BETWEEN 0 AND 4194304))`,
			`CREATE TABLE categories (category_id CHAR(36) PRIMARY KEY, account_id CHAR(36) NOT NULL, name VARCHAR(40) NOT NULL, version_no BIGINT NOT NULL DEFAULT 1, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), UNIQUE(account_id,name), FOREIGN KEY(account_id) REFERENCES accounts(account_id))`,
			`CREATE TABLE mailbox_entries (entry_id CHAR(36) PRIMARY KEY, account_id CHAR(36) NOT NULL, content_id CHAR(36) NOT NULL, folder VARCHAR(16) NOT NULL, is_read BOOLEAN NOT NULL DEFAULT FALSE, category_id CHAR(36), version_no BIGINT NOT NULL DEFAULT 1, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), UNIQUE(account_id,content_id), FOREIGN KEY(account_id) REFERENCES accounts(account_id), FOREIGN KEY(content_id) REFERENCES message_contents(content_id), FOREIGN KEY(category_id) REFERENCES categories(category_id), CONSTRAINT mailbox_folder_known CHECK(folder IN('INBOX','SENT','ARCHIVE','SPAM','TRASH')))`,
			`CREATE INDEX mailbox_folder_page ON mailbox_entries(account_id,folder,created_at DESC,entry_id DESC)`,
			`CREATE INDEX mailbox_category_page ON mailbox_entries(account_id,category_id,created_at DESC,entry_id DESC)`,
			`CREATE TABLE drafts (draft_id CHAR(36) PRIMARY KEY, account_id CHAR(36) NOT NULL, version_no BIGINT NOT NULL DEFAULT 1, subject VARCHAR(998) NOT NULL, text_body MEDIUMTEXT NOT NULL, html_body MEDIUMTEXT NOT NULL, to_json JSON NOT NULL, cc_json JSON NOT NULL, bcc_json JSON NOT NULL, mode VARCHAR(16) NOT NULL DEFAULT 'COMPOSE', source_content_id CHAR(36), created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), FOREIGN KEY(account_id) REFERENCES accounts(account_id), FOREIGN KEY(source_content_id) REFERENCES message_contents(content_id), CONSTRAINT draft_mode_known CHECK(mode IN('COMPOSE','REPLY','REPLY_ALL','FORWARD')))`,
			`CREATE INDEX drafts_owner_page ON drafts(account_id,updated_at DESC,draft_id DESC)`,
			`CREATE TABLE draft_attachments (attachment_id CHAR(36) PRIMARY KEY, draft_id CHAR(36) NOT NULL, object_id CHAR(36) NOT NULL, file_name VARCHAR(255) NOT NULL, media_type VARCHAR(120) NOT NULL, sha256 CHAR(64) NOT NULL, byte_size BIGINT NOT NULL, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), FOREIGN KEY(draft_id) REFERENCES drafts(draft_id) ON DELETE CASCADE, FOREIGN KEY(object_id) REFERENCES stored_objects(object_id), CONSTRAINT draft_attachment_size CHECK(byte_size BETWEEN 0 AND 4194304))`,
		}})
		result = append(result, Migration{Version: 4, Name: "send_intents", Statements: []string{
			`CREATE TABLE send_intents (intent_id CHAR(36) PRIMARY KEY, account_id CHAR(36) NOT NULL, draft_id CHAR(36) NOT NULL, draft_version BIGINT NOT NULL, request_key VARCHAR(128) NOT NULL, payload_sha256 CHAR(64) NOT NULL, dispatch_scope_id CHAR(36) NOT NULL UNIQUE, content_id CHAR(36) NOT NULL, raw_object_id CHAR(36) NOT NULL, raw_sha256 CHAR(64) NOT NULL, raw_size BIGINT NOT NULL, sender_address VARCHAR(254) NOT NULL, envelope_json JSON NOT NULL, state VARCHAR(24) NOT NULL DEFAULT 'SUBMITTED_LOCAL', created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), UNIQUE(account_id,request_key), FOREIGN KEY(account_id) REFERENCES accounts(account_id), FOREIGN KEY(content_id) REFERENCES message_contents(content_id), FOREIGN KEY(raw_object_id) REFERENCES stored_objects(object_id), CONSTRAINT send_state_known CHECK(state IN('SUBMITTED_LOCAL','CANCELLED','IN_PROGRESS')))`,
			`CREATE TABLE mailbox_outbox (event_id CHAR(36) PRIMARY KEY, aggregate_id CHAR(36) NOT NULL, topic VARCHAR(100) NOT NULL, message_key VARCHAR(160) NOT NULL, payload JSON NOT NULL, attempts INT NOT NULL DEFAULT 0, next_attempt_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), published_at TIMESTAMP(6), created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), UNIQUE(topic,message_key), INDEX mailbox_outbox_pending(published_at,next_attempt_at,created_at))`,
			`CREATE TABLE ingress_import_receipts (spool_id CHAR(36) NOT NULL, recipient_account_id CHAR(36) NOT NULL, raw_sha256 CHAR(64) NOT NULL, entry_id CHAR(36) NOT NULL, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(spool_id,recipient_account_id), FOREIGN KEY(recipient_account_id) REFERENCES accounts(account_id), FOREIGN KEY(entry_id) REFERENCES mailbox_entries(entry_id))`,
		}})
	case "ingress":
		result = append(result, Migration{Version: 2, Name: "accepted_spool", Statements: []string{
			`CREATE TABLE accepted_spools (spool_id CHAR(36) PRIMARY KEY, source_receipt VARCHAR(160) NOT NULL UNIQUE, mail_from VARCHAR(254) NOT NULL, raw_object_id CHAR(36) NOT NULL, raw_sha256 CHAR(64) NOT NULL, raw_size BIGINT NOT NULL, state VARCHAR(24) NOT NULL DEFAULT 'ACCEPTED', accepted_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), acked_at TIMESTAMP(6), FOREIGN KEY(raw_object_id) REFERENCES stored_objects(object_id), CONSTRAINT spool_state_known CHECK(state IN('ACCEPTED','ACKED','GC_ELIGIBLE')))`,
			`CREATE TABLE accepted_recipients (spool_id CHAR(36) NOT NULL, ordinal_no INT NOT NULL, account_id CHAR(36) NOT NULL, address VARCHAR(254) NOT NULL, PRIMARY KEY(spool_id,ordinal_no), UNIQUE(spool_id,account_id), FOREIGN KEY(spool_id) REFERENCES accepted_spools(spool_id) ON DELETE CASCADE)`,
			`CREATE TABLE ingress_outbox (event_id CHAR(36) PRIMARY KEY, aggregate_id CHAR(36) NOT NULL, topic VARCHAR(100) NOT NULL, message_key VARCHAR(160) NOT NULL, payload JSON NOT NULL, attempts INT NOT NULL DEFAULT 0, next_attempt_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), published_at TIMESTAMP(6), created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), UNIQUE(topic,message_key), INDEX ingress_outbox_pending(published_at,next_attempt_at,created_at))`,
		}})
	case "delivery":
		result = append(result, Migration{Version: 2, Name: "delivery_state", Statements: []string{
			`CREATE TABLE dispatch_scopes (scope_id CHAR(36) PRIMARY KEY, source_intent_id CHAR(36) NOT NULL UNIQUE, source_service VARCHAR(32) NOT NULL, raw_sha256 CHAR(64) NOT NULL, raw_size BIGINT NOT NULL, sender_address VARCHAR(254) NOT NULL, state VARCHAR(24) NOT NULL DEFAULT 'QUEUED', ever_started BOOLEAN NOT NULL DEFAULT FALSE, version_no BIGINT NOT NULL DEFAULT 1, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), CONSTRAINT scope_state_known CHECK(state IN('QUEUED','CANCELLED','STARTED','COMPLETED')))`,
			`CREATE TABLE delivery_jobs (job_id CHAR(36) PRIMARY KEY, scope_id CHAR(36) NOT NULL, recipient VARCHAR(254) NOT NULL, state VARCHAR(32) NOT NULL DEFAULT 'QUEUED', attempt_count INT NOT NULL DEFAULT 0, next_attempt_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), active_epoch BIGINT NOT NULL DEFAULT 0, worker_id CHAR(36), lease_until TIMESTAMP(6), updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6), UNIQUE(scope_id,recipient), FOREIGN KEY(scope_id) REFERENCES dispatch_scopes(scope_id), CONSTRAINT job_state_known CHECK(state IN('QUEUED','STARTED','RETRY_WAIT','NEXT_HOP_ACCEPTED','PERMANENT_FAILURE','UNKNOWN','CANCELLED')))`,
			`CREATE TABLE delivery_attempts (attempt_id CHAR(36) PRIMARY KEY, job_id CHAR(36) NOT NULL, epoch_no BIGINT NOT NULL, worker_id CHAR(36) NOT NULL, started_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), completed_at TIMESTAMP(6), last_stage VARCHAR(32) NOT NULL, data_submitted BOOLEAN NOT NULL DEFAULT FALSE, smtp_code INT, outcome VARCHAR(32), evidence_sha256 CHAR(64), duplicate_risk_ack BOOLEAN NOT NULL DEFAULT FALSE, prior_attempt_id CHAR(36), UNIQUE(job_id,epoch_no), FOREIGN KEY(job_id) REFERENCES delivery_jobs(job_id), FOREIGN KEY(prior_attempt_id) REFERENCES delivery_attempts(attempt_id))`,
			`CREATE TABLE delivery_retry_requests (scope_id CHAR(36) NOT NULL, request_key VARCHAR(128) NOT NULL, recipient VARCHAR(254) NOT NULL, prior_attempt_id CHAR(36) NOT NULL, created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(scope_id,request_key), FOREIGN KEY(scope_id) REFERENCES dispatch_scopes(scope_id), FOREIGN KEY(prior_attempt_id) REFERENCES delivery_attempts(attempt_id))`,
			`CREATE TABLE delivery_events (source_service VARCHAR(32) NOT NULL, source_intent_id CHAR(36) NOT NULL, payload_sha256 CHAR(64) NOT NULL, processed_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY(source_service,source_intent_id))`,
		}})
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
