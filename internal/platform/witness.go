package platform

import (
	"bufio"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/google/uuid"
)

const (
	maxWitnessBytes        = 10 * 1024 * 1024
	maxWitnessTransactions = 10_000
)

type receipt struct {
	sequence int64
	digest   string
}

type installedMigration struct {
	name   string
	digest string
}

type CommitUnknownError struct {
	TransactionID string
	Cause         error
}

func (errorValue *CommitUnknownError) Error() string { return "transaction outcome must be reconciled" }
func (errorValue *CommitUnknownError) Unwrap() error { return errorValue.Cause }

// Witness binds database transactions to a durable, service-owned journal.
type Witness struct {
	mu            sync.Mutex
	database      *sql.DB
	root          string
	service       string
	source        string
	generation    string
	lockPath      string
	journal       *os.File
	chain         string
	nextSequence  int64
	lastCommitted int64
	state         string
	reason        string
}

func NewWitness(database *sql.DB, root, service, source string, migrations []Migration) (*Witness, error) {
	generationBytes, err := os.ReadFile(filepath.Join(root, "generation.txt"))
	if err != nil {
		return nil, fmt.Errorf("read witness generation: %w", err)
	}
	generation := strings.TrimSpace(string(generationBytes))
	if _, err := uuid.Parse(generation); err != nil {
		return nil, fmt.Errorf("invalid witness generation")
	}
	lockPath := filepath.Join(root, "active-writer.lock")
	lock, err := os.OpenFile(lockPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return nil, fmt.Errorf("witness already has an active or unreconciled writer: %w", err)
	}
	if _, err := fmt.Fprintf(lock, "%d\n", os.Getpid()); err != nil {
		_ = lock.Close()
		_ = os.Remove(lockPath)
		return nil, err
	}
	if err := lock.Sync(); err != nil {
		_ = lock.Close()
		_ = os.Remove(lockPath)
		return nil, err
	}
	_ = lock.Close()
	witness := &Witness{database: database, root: root, service: service, source: source,
		generation: generation, lockPath: lockPath, nextSequence: 1,
		state: "NOT_RECONCILED", reason: "NOT_CHECKED"}
	if err := witness.initialize(context.Background(), migrations); err != nil && witness.state != "WAITING_DEPENDENCY" {
		_ = witness.Close()
		return nil, err
	}
	return witness, nil
}

func (witness *Witness) Initialize(ctx context.Context, migrations []Migration) error {
	witness.mu.Lock()
	defer witness.mu.Unlock()
	if witness.state == "READY" {
		return nil
	}
	return witness.initialize(ctx, migrations)
}

func (witness *Witness) initialize(ctx context.Context, migrations []Migration) error {
	witness.chain = SHA256([]byte("GuiHongWitness/1.0|" + witness.generation))
	if witness.journal != nil {
		_ = witness.journal.Close()
		witness.journal = nil
	}
	connection, err := witness.database.Conn(ctx)
	if err != nil {
		witness.state, witness.reason = "WAITING_DEPENDENCY", "DATABASE_UNAVAILABLE"
		return err
	}
	defer connection.Close()
	if err := connection.PingContext(ctx); err != nil {
		witness.state, witness.reason = "WAITING_DEPENDENCY", "DATABASE_UNAVAILABLE"
		return err
	}
	if err := witness.reconcileSchema(ctx, connection, migrations); err != nil {
		witness.state, witness.reason = "NOT_RECONCILED", "SCHEMA_WITNESS_MISMATCH"
		return err
	}
	var actualGeneration string
	var lastSequence int64
	if err := connection.QueryRowContext(ctx,
		"SELECT generation,last_committed_seq FROM foundation_meta WHERE singleton=1").Scan(&actualGeneration, &lastSequence); err != nil {
		witness.state, witness.reason = "NOT_RECONCILED", "DATABASE_MARKER_MISSING"
		return err
	}
	if !Same(actualGeneration, witness.generation) {
		witness.state, witness.reason = "NOT_RECONCILED", "GENERATION_MISMATCH"
		return fmt.Errorf("generation mismatch")
	}
	databaseReceipts, err := readDatabaseReceipts(ctx, connection)
	if err != nil {
		return err
	}
	prepared, outcomes, maximumPrepared, err := witness.readJournal()
	if err != nil {
		witness.state, witness.reason = "NOT_RECONCILED", "WITNESS_CHAIN_FAILURE"
		return err
	}
	if len(prepared) == 0 && len(databaseReceipts) > 0 {
		witness.state, witness.reason = "NOT_RECONCILED", "MISSING_WITNESS_FOR_COMMITTED_STATE"
		return fmt.Errorf("missing witness for committed state")
	}
	journal, err := os.OpenFile(filepath.Join(witness.root, "transactions.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	witness.journal = journal
	maximumCommitted := int64(0)
	sequences := make([]int64, 0, len(prepared))
	bySequence := make(map[int64]string, len(prepared))
	for id, item := range prepared {
		sequences = append(sequences, item.sequence)
		bySequence[item.sequence] = id
	}
	sort.Slice(sequences, func(i, j int) bool { return sequences[i] < sequences[j] })
	for _, sequence := range sequences {
		id := bySequence[sequence]
		item := prepared[id]
		databaseReceipt, exists := databaseReceipts[id]
		outcome := outcomes[id]
		if outcome == "A" {
			if exists {
				return fmt.Errorf("aborted witness has a committed receipt")
			}
			continue
		}
		if !exists || databaseReceipt != item {
			return fmt.Errorf("committed or uncertain witness missing exact database receipt")
		}
		delete(databaseReceipts, id)
		if sequence > maximumCommitted {
			maximumCommitted = sequence
		}
		if outcome != "C" {
			if err := witness.append(sequence, id, "C", item.digest); err != nil {
				return err
			}
		}
	}
	if len(databaseReceipts) != 0 || maximumCommitted != lastSequence {
		return fmt.Errorf("unwitnessed database state or old snapshot")
	}
	witness.nextSequence = maximumPrepared + 1
	witness.lastCommitted = maximumCommitted
	witness.state, witness.reason = "READY", "RECONCILED"
	return nil
}

func readDatabaseReceipts(ctx context.Context, connection *sql.Conn) (map[string]receipt, error) {
	rows, err := connection.QueryContext(ctx, "SELECT tx_id,sequence_no,payload_sha256 FROM tx_receipts LIMIT 10001")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make(map[string]receipt)
	for rows.Next() {
		var id, digest string
		var sequence int64
		if err := rows.Scan(&id, &sequence, &digest); err != nil {
			return nil, err
		}
		result[id] = receipt{sequence: sequence, digest: digest}
	}
	if len(result) > maxWitnessTransactions {
		return nil, fmt.Errorf("witness capacity exceeded")
	}
	return result, rows.Err()
}

func (witness *Witness) readJournal() (map[string]receipt, map[string]string, int64, error) {
	path := filepath.Join(witness.root, "transactions.log")
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]receipt{}, map[string]string{}, 0, nil
	}
	if err != nil {
		return nil, nil, 0, err
	}
	if !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 || info.Size() > maxWitnessBytes {
		return nil, nil, 0, fmt.Errorf("witness log capacity or identity failure")
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, nil, 0, err
	}
	defer file.Close()
	prepared := make(map[string]receipt)
	outcomes := make(map[string]string)
	maximumPrepared := int64(0)
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		fields := strings.Split(scanner.Text(), "|")
		if len(fields) != 6 {
			return nil, nil, 0, fmt.Errorf("malformed witness record")
		}
		sequence, err := strconv.ParseInt(fields[0], 10, 64)
		if err != nil {
			return nil, nil, 0, err
		}
		if _, err := uuid.Parse(fields[1]); err != nil {
			return nil, nil, 0, err
		}
		content := strings.Join(fields[:5], "|")
		if !Same(fields[4], witness.chain) || !Same(fields[5], SHA256([]byte(content))) || len(fields[3]) != 64 {
			return nil, nil, 0, fmt.Errorf("witness chain failure")
		}
		witness.chain = fields[5]
		if fields[2] == "P" {
			if sequence != maximumPrepared+1 {
				return nil, nil, 0, fmt.Errorf("witness sequence failure")
			}
			if _, exists := prepared[fields[1]]; exists {
				return nil, nil, 0, fmt.Errorf("duplicate prepared transaction")
			}
			maximumPrepared = sequence
			prepared[fields[1]] = receipt{sequence: sequence, digest: fields[3]}
			continue
		}
		item, exists := prepared[fields[1]]
		if !exists || item.sequence != sequence || !Same(item.digest, fields[3]) ||
			(fields[2] != "C" && fields[2] != "A" && fields[2] != "U") {
			return nil, nil, 0, fmt.Errorf("unbound witness outcome")
		}
		if previous := outcomes[fields[1]]; previous != "" && previous != "U" {
			return nil, nil, 0, fmt.Errorf("final witness overwritten")
		}
		outcomes[fields[1]] = fields[2]
	}
	return prepared, outcomes, maximumPrepared, scanner.Err()
}

func (witness *Witness) reconcileSchema(ctx context.Context, connection *sql.Conn, migrations []Migration) error {
	pending := filepath.Join(witness.root, "schema-migration.pending")
	if _, err := os.Lstat(pending); err == nil {
		return fmt.Errorf("incomplete schema migration requires independent reconciliation")
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	var markerCount int
	if err := connection.QueryRowContext(ctx,
		"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='foundation_meta'").Scan(&markerCount); err != nil {
		return err
	}
	bootstrap := markerCount == 0
	if bootstrap {
		permit := filepath.Join(witness.root, "bootstrap-permit")
		consumed := filepath.Join(witness.root, "bootstrap-consumed")
		if _, err := os.Lstat(permit); err != nil {
			return fmt.Errorf("missing database marker without unused virgin authority")
		}
		if _, err := os.Lstat(consumed); err == nil {
			return fmt.Errorf("bootstrap authority already consumed")
		}
		if err := os.Rename(permit, consumed); err != nil {
			return err
		}
		if err := durableNew(pending, witness.generation+"|"+witness.source+"|VIRGIN\n"); err != nil {
			return err
		}
		if _, err := connection.ExecContext(ctx, `CREATE TABLE schema_migrations (version INT PRIMARY KEY, name VARCHAR(100) NOT NULL, sha256 CHAR(64) NOT NULL, installed_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6))`); err != nil {
			return err
		}
	}
	installed, err := installedMigrations(ctx, connection)
	if err != nil {
		return err
	}
	for _, migration := range migrations {
		digest := migrationDigest(migration)
		if actual, exists := installed[migration.Version]; exists {
			if actual.name != migration.Name || !Same(actual.digest, digest) {
				return fmt.Errorf("installed migration mismatch")
			}
			continue
		}
		if !bootstrap {
			actualHistory, err := schemaHistoryHash(ctx, connection)
			if err != nil {
				return err
			}
			expected, err := os.ReadFile(filepath.Join(witness.root, "schema-history.sha256"))
			if err != nil || !Same(strings.TrimSpace(string(expected)), actualHistory) {
				return fmt.Errorf("schema witness mismatch before migration")
			}
			if err := durableNew(pending, witness.generation+"|"+witness.source+"|"+actualHistory+"\n"); err != nil {
				return err
			}
		}
		for _, statement := range migration.Statements {
			if _, err := connection.ExecContext(ctx, statement); err != nil {
				return fmt.Errorf("migration %d failed: %w", migration.Version, err)
			}
		}
		if _, err := connection.ExecContext(ctx, "INSERT INTO schema_migrations(version,name,sha256) VALUES(?,?,?)",
			migration.Version, migration.Name, digest); err != nil {
			return err
		}
	}
	if bootstrap {
		if _, err := connection.ExecContext(ctx,
			"INSERT INTO foundation_meta(singleton,generation,last_committed_seq) VALUES(1,?,0)", witness.generation); err != nil {
			return err
		}
	}
	history, err := schemaHistoryHash(ctx, connection)
	if err != nil {
		return err
	}
	expectedPath := filepath.Join(witness.root, "schema-history.sha256")
	if bootstrap {
		if err := durableNew(expectedPath, history+"\n"); err != nil {
			return err
		}
	} else if current, err := os.ReadFile(expectedPath); err != nil || !Same(strings.TrimSpace(string(current)), history) {
		next := expectedPath + ".next"
		if err := durableNew(next, history+"\n"); err != nil {
			return err
		}
		if err := os.Remove(expectedPath); err != nil {
			return err
		}
		if err := os.Rename(next, expectedPath); err != nil {
			return err
		}
	}
	completed := filepath.Join(witness.root, "schema-migration-"+uuid.NewString()+".completed")
	if _, err := os.Lstat(pending); err == nil {
		if err := os.Rename(pending, completed); err != nil {
			return err
		}
	}
	return nil
}

func installedMigrations(ctx context.Context, connection *sql.Conn) (map[int]installedMigration, error) {
	rows, err := connection.QueryContext(ctx, "SELECT version,name,sha256 FROM schema_migrations ORDER BY version")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make(map[int]installedMigration)
	for rows.Next() {
		var version int
		var name, digest string
		if err := rows.Scan(&version, &name, &digest); err != nil {
			return nil, err
		}
		result[version] = installedMigration{name: name, digest: digest}
	}
	return result, rows.Err()
}

func schemaHistoryHash(ctx context.Context, connection *sql.Conn) (string, error) {
	rows, err := connection.QueryContext(ctx, "SELECT version,name,sha256 FROM schema_migrations ORDER BY version")
	if err != nil {
		return "", err
	}
	defer rows.Close()
	var builder strings.Builder
	for rows.Next() {
		var version int
		var name, digest string
		if err := rows.Scan(&version, &name, &digest); err != nil {
			return "", err
		}
		fmt.Fprintf(&builder, "%d|%s|%s\n", version, name, digest)
	}
	return SHA256([]byte(builder.String())), rows.Err()
}

func durableNew(path, value string) error {
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return err
	}
	if _, err := io.WriteString(file, value); err != nil {
		_ = file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return err
	}
	return file.Close()
}

func (witness *Witness) Write(ctx context.Context, descriptor string, operation func(*sql.Tx) error) error {
	witness.mu.Lock()
	defer witness.mu.Unlock()
	if witness.state != "READY" {
		return fmt.Errorf("not reconciled")
	}
	sequence := witness.nextSequence
	witness.nextSequence++
	id := uuid.NewString()
	digest := SHA256([]byte(descriptor))
	if err := witness.append(sequence, id, "P", digest); err != nil {
		witness.state, witness.reason = "NOT_RECONCILED", "WITNESS_UNAVAILABLE"
		return err
	}
	tx, err := witness.database.BeginTx(ctx, nil)
	if err != nil {
		_ = witness.append(sequence, id, "A", digest)
		return err
	}
	commitIssued := false
	fail := func(cause error) error {
		if commitIssued {
			witness.state, witness.reason = "NOT_RECONCILED", "COMMIT_UNKNOWN"
			_ = witness.append(sequence, id, "U", digest)
			return &CommitUnknownError{TransactionID: id, Cause: cause}
		}
		if rollbackError := tx.Rollback(); rollbackError != nil && !errors.Is(rollbackError, sql.ErrTxDone) {
			witness.state, witness.reason = "NOT_RECONCILED", "ROLLBACK_UNKNOWN"
			return errors.Join(cause, rollbackError)
		}
		if appendError := witness.append(sequence, id, "A", digest); appendError != nil {
			witness.state, witness.reason = "NOT_RECONCILED", "WITNESS_UNAVAILABLE"
			return errors.Join(cause, appendError)
		}
		return cause
	}
	var generation string
	var currentSequence int64
	if err := tx.QueryRowContext(ctx,
		"SELECT generation,last_committed_seq FROM foundation_meta WHERE singleton=1 FOR UPDATE").Scan(&generation, &currentSequence); err != nil {
		return fail(err)
	}
	if !Same(generation, witness.generation) || currentSequence != witness.lastCommitted {
		witness.state, witness.reason = "NOT_RECONCILED", "DATABASE_MARKER_MISMATCH"
		return fail(fmt.Errorf("database marker mismatch"))
	}
	if err := operation(tx); err != nil {
		return fail(err)
	}
	if _, err := tx.ExecContext(ctx, "INSERT INTO tx_receipts(tx_id,sequence_no,payload_sha256) VALUES(?,?,?)",
		id, sequence, digest); err != nil {
		return fail(err)
	}
	result, err := tx.ExecContext(ctx,
		"UPDATE foundation_meta SET last_committed_seq=? WHERE singleton=1 AND generation=?", sequence, witness.generation)
	if err != nil {
		return fail(err)
	}
	if rows, err := result.RowsAffected(); err != nil || rows != 1 {
		return fail(fmt.Errorf("generation changed during write"))
	}
	commitIssued = true
	if err := tx.Commit(); err != nil {
		return fail(err)
	}
	if err := witness.append(sequence, id, "C", digest); err != nil {
		witness.state, witness.reason = "NOT_RECONCILED", "WITNESS_UNAVAILABLE"
		return &CommitUnknownError{TransactionID: id, Cause: err}
	}
	witness.lastCommitted = sequence
	return nil
}

func (witness *Witness) append(sequence int64, id, outcome, payload string) error {
	if witness.journal == nil {
		return fmt.Errorf("witness journal unavailable")
	}
	info, err := witness.journal.Stat()
	if err != nil || info.Size() >= maxWitnessBytes || sequence > maxWitnessTransactions {
		return fmt.Errorf("witness capacity exhausted")
	}
	content := fmt.Sprintf("%d|%s|%s|%s|%s", sequence, id, outcome, payload, witness.chain)
	digest := SHA256([]byte(content))
	if _, err := io.WriteString(witness.journal, content+"|"+digest+"\n"); err != nil {
		return err
	}
	if err := witness.journal.Sync(); err != nil {
		return err
	}
	witness.chain = digest
	return nil
}

func (witness *Witness) VerifyCurrent(ctx context.Context) bool {
	witness.mu.Lock()
	defer witness.mu.Unlock()
	if witness.state != "READY" {
		return false
	}
	var generation string
	var sequence int64
	if err := witness.database.QueryRowContext(ctx,
		"SELECT generation,last_committed_seq FROM foundation_meta WHERE singleton=1").Scan(&generation, &sequence); err != nil {
		return false
	}
	if !Same(generation, witness.generation) || sequence != witness.lastCommitted {
		witness.state, witness.reason = "NOT_RECONCILED", "DATABASE_MARKER_MISMATCH"
		return false
	}
	return true
}

func (witness *Witness) Block(reason string) {
	witness.mu.Lock()
	defer witness.mu.Unlock()
	witness.state, witness.reason = "NOT_RECONCILED", reason
}

func (witness *Witness) State() (string, string) {
	witness.mu.Lock()
	defer witness.mu.Unlock()
	return witness.state, witness.reason
}

func (witness *Witness) Generation() string { return witness.generation }

func (witness *Witness) Close() error {
	witness.mu.Lock()
	defer witness.mu.Unlock()
	witness.state = "STOPPED"
	var result error
	if witness.journal != nil {
		result = witness.journal.Close()
		witness.journal = nil
	}
	if err := os.Remove(witness.lockPath); err != nil && !errors.Is(err, os.ErrNotExist) {
		result = errors.Join(result, err)
	}
	return result
}
