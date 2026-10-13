CREATE TABLE foundation_meta (
 singleton TINYINT PRIMARY KEY, generation CHAR(36) NOT NULL, last_committed_seq BIGINT NOT NULL,
 CONSTRAINT single_generation CHECK(singleton=1)
);
CREATE TABLE tx_receipts (
 tx_id CHAR(36) PRIMARY KEY, sequence_no BIGINT NOT NULL UNIQUE, payload_sha256 CHAR(64) NOT NULL
);
CREATE TABLE stored_objects (
 object_id CHAR(36) PRIMARY KEY, object_key VARCHAR(200) NOT NULL UNIQUE,
 authority_key VARCHAR(128) NOT NULL, sha256 CHAR(64) NOT NULL, byte_size BIGINT NOT NULL,
 lifecycle VARCHAR(24) NOT NULL, in_flight INT NOT NULL DEFAULT 0,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 CONSTRAINT nonnegative_size CHECK(byte_size>=0), CONSTRAINT nonnegative_inflight CHECK(in_flight>=0)
);
CREATE TABLE object_refs (
 ref_kind VARCHAR(32) NOT NULL, ref_id VARCHAR(64) NOT NULL, object_id CHAR(36) NOT NULL,
 PRIMARY KEY(ref_kind,ref_id,object_id), FOREIGN KEY(object_id) REFERENCES stored_objects(object_id)
);
