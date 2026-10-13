package platform

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net"
	"regexp"
	"sync"
	"time"

	"github.com/google/uuid"
)

var referencePartPattern = regexp.MustCompile(`^[a-zA-Z0-9._:@/-]{1,64}$`)

type Blob struct {
	ID       string `json:"id"`
	Key      string `json:"key"`
	SHA256   string `json:"sha256"`
	Size     int64  `json:"size"`
	State    string `json:"state"`
	InFlight int    `json:"in_flight"`
}

type ObjectRepository struct {
	mu         sync.Mutex
	database   *sql.DB
	witness    *Witness
	store      *S3Client
	draining   func() bool
	reconciled bool
}

func NewObjectRepository(database *sql.DB, witness *Witness, store *S3Client, draining func() bool) *ObjectRepository {
	return &ObjectRepository{database: database, witness: witness, store: store, draining: draining}
}

func (repository *ObjectRepository) Reconciled() bool {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	return repository.reconciled
}

func (repository *ObjectRepository) requireWritable(ctx context.Context) error {
	if repository.draining() || !repository.witness.VerifyCurrent(ctx) || !repository.reconciled {
		return fmt.Errorf("service is not writable")
	}
	return nil
}

func (repository *ObjectRepository) Reconcile(ctx context.Context) bool {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	repository.reconciled = false
	if !repository.witness.VerifyCurrent(ctx) || !repository.store.Ready(ctx) {
		return false
	}
	rows, err := repository.database.QueryContext(ctx, `SELECT DISTINCT o.object_id,o.object_key,o.sha256,o.byte_size,o.lifecycle,o.in_flight
		FROM stored_objects o JOIN object_refs r ON r.object_id=o.object_id LIMIT 10001`)
	if err != nil {
		repository.witness.Block("OBJECTS_NOT_RECONCILED")
		return false
	}
	defer rows.Close()
	count := 0
	for rows.Next() {
		count++
		if count > 10000 {
			repository.witness.Block("OBJECTS_NOT_RECONCILED")
			return false
		}
		var blob Blob
		if err := rows.Scan(&blob.ID, &blob.Key, &blob.SHA256, &blob.Size, &blob.State, &blob.InFlight); err != nil || blob.State != "LIVE" {
			repository.witness.Block("OBJECTS_NOT_RECONCILED")
			return false
		}
		bytes, err := repository.store.Get(ctx, blob.Key)
		if err != nil || !Same(blob.SHA256, SHA256(bytes)) {
			repository.witness.Block("OBJECTS_NOT_RECONCILED")
			return false
		}
	}
	if rows.Err() != nil {
		repository.witness.Block("OBJECTS_NOT_RECONCILED")
		return false
	}
	repository.reconciled = true
	return true
}

func (repository *ObjectRepository) Metadata(ctx context.Context, id string) (Blob, error) {
	if _, err := uuid.Parse(id); err != nil {
		return Blob{}, fmt.Errorf("invalid object identity")
	}
	var blob Blob
	err := repository.database.QueryRowContext(ctx, `SELECT object_id,object_key,sha256,byte_size,lifecycle,in_flight
		FROM stored_objects WHERE object_id=?`, id).Scan(&blob.ID, &blob.Key, &blob.SHA256, &blob.Size, &blob.State, &blob.InFlight)
	return blob, err
}

func (repository *ObjectRepository) Stage(ctx context.Context, id, authority string, data []byte) (Blob, error) {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	if err := repository.requireWritable(ctx); err != nil {
		return Blob{}, err
	}
	if _, err := uuid.Parse(id); err != nil || authority == "" || len(authority) > 128 || len(data) > MaxObjectBytes {
		return Blob{}, fmt.Errorf("invalid object authority or size")
	}
	digest := SHA256(data)
	key := "objects/" + repository.witness.Generation() + "/" + id
	err := repository.witness.Write(ctx, "object-stage|"+id+"|"+authority+"|"+digest, func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, `INSERT INTO stored_objects
			(object_id,object_key,authority_key,sha256,byte_size,lifecycle,in_flight)
			VALUES(?,?,?,?,?,'STAGED',1)`, id, key, authority, digest, len(data))
		return err
	})
	if err != nil {
		return Blob{}, err
	}
	if err := repository.store.Put(ctx, key, data); err != nil {
		if definitelyNotConnected(err) && repository.witness.VerifyCurrent(ctx) {
			_ = repository.orphan(ctx, id)
		}
		return Blob{}, err
	}
	actual, err := repository.store.Get(ctx, key)
	if err != nil || !Same(digest, SHA256(actual)) {
		if err == nil {
			err = fmt.Errorf("staged object hash mismatch")
		}
		return Blob{}, err
	}
	return repository.Metadata(ctx, id)
}

func (repository *ObjectRepository) Reference(ctx context.Context, id, kind, referenceID string) (Blob, error) {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	if err := repository.requireWritable(ctx); err != nil {
		return Blob{}, err
	}
	if !referencePartPattern.MatchString(kind) || !referencePartPattern.MatchString(referenceID) {
		return Blob{}, fmt.Errorf("invalid object reference")
	}
	blob, err := repository.Metadata(ctx, id)
	if err != nil {
		return Blob{}, err
	}
	actual, err := repository.store.Get(ctx, blob.Key)
	if err != nil || !Same(blob.SHA256, SHA256(actual)) {
		return Blob{}, fmt.Errorf("staged object hash mismatch")
	}
	err = repository.witness.Write(ctx, "object-reference|"+id+"|"+kind+"|"+referenceID+"|"+blob.SHA256, func(tx *sql.Tx) error {
		var state string
		if err := tx.QueryRowContext(ctx, "SELECT lifecycle FROM stored_objects WHERE object_id=? FOR UPDATE", id).Scan(&state); err != nil {
			return err
		}
		if state != "STAGED" && state != "LIVE" {
			return fmt.Errorf("object has no reference eligibility")
		}
		if _, err := tx.ExecContext(ctx, "INSERT INTO object_refs(ref_kind,ref_id,object_id) VALUES(?,?,?)", kind, referenceID, id); err != nil {
			return err
		}
		result, err := tx.ExecContext(ctx, "UPDATE stored_objects SET lifecycle='LIVE',in_flight=0 WHERE object_id=?", id)
		if err != nil {
			return err
		}
		rows, err := result.RowsAffected()
		if err != nil || rows != 1 {
			return fmt.Errorf("object state changed")
		}
		return nil
	})
	if err != nil {
		var unknown *CommitUnknownError
		if !errors.As(err, &unknown) && blob.State == "STAGED" && repository.witness.VerifyCurrent(ctx) {
			_ = repository.orphan(ctx, id)
		}
		return Blob{}, err
	}
	return repository.Metadata(ctx, id)
}

func (repository *ObjectRepository) orphan(ctx context.Context, id string) error {
	return repository.witness.Write(ctx, "object-orphan|"+id, func(tx *sql.Tx) error {
		_, err := tx.ExecContext(ctx, `UPDATE stored_objects SET lifecycle='ORPHAN',in_flight=0
			WHERE object_id=? AND lifecycle='STAGED'
			AND NOT EXISTS(SELECT 1 FROM object_refs WHERE object_id=?)`, id, id)
		return err
	})
}

func (repository *ObjectRepository) Read(ctx context.Context, id string) ([]byte, error) {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	if err := repository.requireWritable(ctx); err != nil {
		return nil, err
	}
	blob, err := repository.Metadata(ctx, id)
	if err != nil || blob.State != "LIVE" {
		return nil, fmt.Errorf("object not confirmed")
	}
	data, err := repository.store.Get(ctx, blob.Key)
	if err != nil || !Same(blob.SHA256, SHA256(data)) {
		repository.reconciled = false
		repository.witness.Block("OBJECTS_NOT_RECONCILED")
		if err == nil {
			err = fmt.Errorf("stored object hash mismatch")
		}
		return nil, err
	}
	return data, nil
}

func (repository *ObjectRepository) Dereference(ctx context.Context, id, kind, referenceID string) error {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	if err := repository.requireWritable(ctx); err != nil {
		return err
	}
	if _, err := uuid.Parse(id); err != nil || !referencePartPattern.MatchString(kind) || !referencePartPattern.MatchString(referenceID) {
		return fmt.Errorf("invalid object reference")
	}
	return repository.witness.Write(ctx, "object-dereference|"+id+"|"+kind+"|"+referenceID, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx, "DELETE FROM object_refs WHERE object_id=? AND ref_kind=? AND ref_id=?", id, kind, referenceID); err != nil {
			return err
		}
		_, err := tx.ExecContext(ctx, `UPDATE stored_objects SET lifecycle='ORPHAN'
			WHERE object_id=? AND lifecycle='LIVE'
			AND NOT EXISTS(SELECT 1 FROM object_refs WHERE object_id=?)`, id, id)
		return err
	})
}

func (repository *ObjectRepository) GC(ctx context.Context) ([]string, error) {
	repository.mu.Lock()
	defer repository.mu.Unlock()
	if err := repository.requireWritable(ctx); err != nil {
		return nil, err
	}
	rows, err := repository.database.QueryContext(ctx, `SELECT object_id,object_key,sha256,byte_size,lifecycle,in_flight
		FROM stored_objects o WHERE lifecycle IN('ORPHAN','DELETING') AND in_flight=0
		AND created_at<DATE_SUB(NOW(6),INTERVAL 60 SECOND)
		AND NOT EXISTS(SELECT 1 FROM object_refs r WHERE r.object_id=o.object_id)
		ORDER BY created_at LIMIT 50`)
	if err != nil {
		return nil, err
	}
	var candidates []Blob
	for rows.Next() {
		var blob Blob
		if err := rows.Scan(&blob.ID, &blob.Key, &blob.SHA256, &blob.Size, &blob.State, &blob.InFlight); err != nil {
			_ = rows.Close()
			return nil, err
		}
		candidates = append(candidates, blob)
	}
	if err := rows.Close(); err != nil {
		return nil, err
	}
	deadline := time.Now().Add(30 * time.Second)
	deleted := make([]string, 0, len(candidates))
	for _, blob := range candidates {
		if time.Now().After(deadline) {
			break
		}
		claimed := false
		err := repository.witness.Write(ctx, "object-gc-claim|"+blob.ID, func(tx *sql.Tx) error {
			result, err := tx.ExecContext(ctx, `UPDATE stored_objects SET lifecycle='DELETING'
				WHERE object_id=? AND lifecycle IN('ORPHAN','DELETING') AND in_flight=0
				AND NOT EXISTS(SELECT 1 FROM object_refs WHERE object_id=?)`, blob.ID, blob.ID)
			if err != nil {
				return err
			}
			count, err := result.RowsAffected()
			claimed = err == nil && count == 1
			return err
		})
		if err != nil {
			return deleted, err
		}
		if !claimed {
			continue
		}
		if err := repository.store.Delete(ctx, blob.Key); err != nil {
			return deleted, err
		}
		err = repository.witness.Write(ctx, "object-gc-complete|"+blob.ID, func(tx *sql.Tx) error {
			result, err := tx.ExecContext(ctx, `UPDATE stored_objects SET lifecycle='DELETED'
				WHERE object_id=? AND lifecycle='DELETING'
				AND NOT EXISTS(SELECT 1 FROM object_refs WHERE object_id=?)`, blob.ID, blob.ID)
			if err != nil {
				return err
			}
			count, err := result.RowsAffected()
			if err != nil || count != 1 {
				return fmt.Errorf("GC state changed")
			}
			return nil
		})
		if err != nil {
			return deleted, err
		}
		deleted = append(deleted, blob.ID)
	}
	return deleted, nil
}

func definitelyNotConnected(err error) bool {
	var operation *net.OpError
	return errors.As(err, &operation) && operation.Op == "dial" && !operation.Timeout()
}
