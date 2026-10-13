CREATE TABLE message_contents (
 content_id CHAR(36) PRIMARY KEY,
 raw_object_id CHAR(36) NOT NULL,
 raw_sha256 CHAR(64) NOT NULL,
 raw_size BIGINT NOT NULL,
 message_id VARCHAR(998),
 from_address VARCHAR(254) NOT NULL,
 from_name VARCHAR(200),
 subject VARCHAR(998) NOT NULL,
 text_body MEDIUMTEXT NOT NULL,
 safe_html MEDIUMTEXT NOT NULL,
 sent_at TIMESTAMP(6),
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE(raw_sha256, raw_size),
 FOREIGN KEY(raw_object_id) REFERENCES stored_objects(object_id),
 CONSTRAINT message_raw_size CHECK(raw_size BETWEEN 1 AND 5242880)
);

CREATE TABLE message_recipients (
 content_id CHAR(36) NOT NULL,
 recipient_kind VARCHAR(3) NOT NULL,
 ordinal_no INT NOT NULL,
 address VARCHAR(254) NOT NULL,
 display_name VARCHAR(200),
 PRIMARY KEY(content_id, recipient_kind, ordinal_no),
 FOREIGN KEY(content_id) REFERENCES message_contents(content_id),
 CONSTRAINT recipient_kind_known CHECK(recipient_kind IN ('TO','CC','BCC'))
);

CREATE TABLE message_attachments (
 attachment_id CHAR(36) PRIMARY KEY,
 content_id CHAR(36) NOT NULL,
 object_id CHAR(36) NOT NULL,
 ordinal_no INT NOT NULL,
 file_name VARCHAR(255) NOT NULL,
 media_type VARCHAR(120) NOT NULL,
 sha256 CHAR(64) NOT NULL,
 byte_size BIGINT NOT NULL,
 UNIQUE(content_id, ordinal_no),
 FOREIGN KEY(content_id) REFERENCES message_contents(content_id),
 FOREIGN KEY(object_id) REFERENCES stored_objects(object_id),
 CONSTRAINT message_attachment_size CHECK(byte_size BETWEEN 0 AND 4194304)
);

CREATE TABLE categories (
 category_id CHAR(36) PRIMARY KEY,
 account_id CHAR(36) NOT NULL,
 name VARCHAR(40) NOT NULL,
 version_no BIGINT NOT NULL DEFAULT 1,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE(account_id, name),
 FOREIGN KEY(account_id) REFERENCES accounts(account_id)
);

CREATE TABLE mailbox_entries (
 entry_id CHAR(36) PRIMARY KEY,
 account_id CHAR(36) NOT NULL,
 content_id CHAR(36) NOT NULL,
 folder VARCHAR(16) NOT NULL,
 is_read BOOLEAN NOT NULL DEFAULT FALSE,
 category_id CHAR(36),
 version_no BIGINT NOT NULL DEFAULT 1,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE(account_id, content_id),
 FOREIGN KEY(account_id) REFERENCES accounts(account_id),
 FOREIGN KEY(content_id) REFERENCES message_contents(content_id),
 FOREIGN KEY(category_id) REFERENCES categories(category_id),
 CONSTRAINT mailbox_folder_known CHECK(folder IN ('INBOX','SENT','ARCHIVE','SPAM','TRASH'))
);
CREATE INDEX mailbox_folder_page ON mailbox_entries(account_id, folder, created_at DESC, entry_id DESC);
CREATE INDEX mailbox_category_page ON mailbox_entries(account_id, category_id, created_at DESC, entry_id DESC);

CREATE TABLE drafts (
 draft_id CHAR(36) PRIMARY KEY,
 account_id CHAR(36) NOT NULL,
 version_no BIGINT NOT NULL DEFAULT 1,
 subject VARCHAR(998) NOT NULL,
 text_body MEDIUMTEXT NOT NULL,
 html_body MEDIUMTEXT NOT NULL,
 to_json JSON NOT NULL,
 cc_json JSON NOT NULL,
 bcc_json JSON NOT NULL,
 mode VARCHAR(16) NOT NULL DEFAULT 'COMPOSE',
 source_content_id CHAR(36),
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 FOREIGN KEY(account_id) REFERENCES accounts(account_id),
 FOREIGN KEY(source_content_id) REFERENCES message_contents(content_id),
 CONSTRAINT draft_mode_known CHECK(mode IN ('COMPOSE','REPLY','REPLY_ALL','FORWARD'))
);
CREATE INDEX drafts_owner_page ON drafts(account_id, updated_at DESC, draft_id DESC);

CREATE TABLE draft_attachments (
 attachment_id CHAR(36) PRIMARY KEY,
 draft_id CHAR(36) NOT NULL,
 object_id CHAR(36) NOT NULL,
 file_name VARCHAR(255) NOT NULL,
 media_type VARCHAR(120) NOT NULL,
 sha256 CHAR(64) NOT NULL,
 byte_size BIGINT NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 FOREIGN KEY(draft_id) REFERENCES drafts(draft_id) ON DELETE CASCADE,
 FOREIGN KEY(object_id) REFERENCES stored_objects(object_id),
 CONSTRAINT draft_attachment_size CHECK(byte_size BETWEEN 0 AND 4194304)
);

