package dev.guihong.platform;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.StandardCopyOption;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import javax.sql.DataSource;
import org.flywaydb.core.Flyway;

/** Local technical transaction witness. No mailbox/spool/dispatch business entities. */
public final class WitnessGate implements AutoCloseable {
    @FunctionalInterface public interface SqlWork<T> { T execute(Connection connection) throws Exception; }
    private record Receipt(long sequence, String digest) {}
    private static final long MAX_BYTES = 10 * 1024 * 1024;
    private static final int MAX_TRANSACTIONS = 10_000;
    private final DataSource database;
    private final Path root;
    private final String service;
    private final String generation;
    private final String source;
    private final FileChannel lockChannel;
    private final FileLock processLock;
    private FileChannel journal;
    private String chain;
    private long nextSequence = 1;
    private long lastCommittedSequence;
    private volatile String state = "NOT_RECONCILED";
    private volatile String reason = "NOT_CHECKED";

    public WitnessGate(DataSource database, Path root, String service, String source) throws IOException {
        this.database = database; this.root = root; this.service = service;this.source=source;
        if (source==null || !source.matches("[0-9a-f]{40}")) throw new IOException("Exact build identity required");
        if (!Files.isDirectory(root) || Files.isSymbolicLink(root)) throw new IOException("Owned witness root missing/unsafe");
        generation = Files.readString(root.resolve("generation.txt"), StandardCharsets.UTF_8).trim();
        UUID.fromString(generation);
        chain = Hashes.sha256("GuiHongWitness/1.0|" + generation);
        lockChannel = FileChannel.open(root.resolve("writer.lock"), StandardOpenOption.CREATE, StandardOpenOption.WRITE);
        processLock = lockChannel.tryLock();
        if (processLock == null) { lockChannel.close(); throw new IOException("Witness already has an active writer"); }
        initialize();
    }

    public synchronized void initialize() {
        if (state.equals("READY")) return;
        chain = Hashes.sha256("GuiHongWitness/1.0|" + generation);
        try (Connection connection = database.getConnection()) {
            if (journal != null) { journal.close(); journal = null; }
            boolean markerExists;
            boolean freshBootstrap=false;
            try (PreparedStatement query = connection.prepareStatement("SHOW TABLES LIKE 'foundation_meta'"); ResultSet rows = query.executeQuery()) {
                markerExists = rows.next();
            }
            if (!markerExists) {
                // A persisted lab permit was created only after independently observing a virgin schema.
                if (!Files.isRegularFile(root.resolve("bootstrap-permit")) || Files.exists(root.resolve("bootstrap-consumed")) || Files.exists(root.resolve("transactions.log"))) {
                    throw new IllegalStateException("Missing database marker without unused virgin authority");
                }
                Files.move(root.resolve("bootstrap-permit"), root.resolve("bootstrap-consumed"));
                freshBootstrap=true;
                Flyway.configure().dataSource(database).locations("classpath:db/migration/" + service).cleanDisabled(true).load().migrate();
                try (PreparedStatement insert = connection.prepareStatement("INSERT INTO foundation_meta(singleton,generation,last_committed_seq) VALUES(1,?,0)")) {
                    insert.setString(1, generation); insert.executeUpdate();
                }
            }
            String actualGeneration; long lastSequence;
            try (PreparedStatement query = connection.prepareStatement("SELECT generation,last_committed_seq FROM foundation_meta WHERE singleton=1"); ResultSet rows = query.executeQuery()) {
                if (!rows.next()) throw new IllegalStateException("Missing generation row");
                actualGeneration = rows.getString(1); lastSequence = rows.getLong(2);
            }
            if (!Hashes.same(generation, actualGeneration)) throw new IllegalStateException("Generation mismatch");
            Map<String, Receipt> databaseReceipts = new HashMap<>();
            try (PreparedStatement query = connection.prepareStatement("SELECT tx_id,sequence_no,payload_sha256 FROM tx_receipts LIMIT 10001"); ResultSet rows = query.executeQuery()) {
                while (rows.next()) databaseReceipts.put(rows.getString(1), new Receipt(rows.getLong(2), rows.getString(3)));
            }
            if (databaseReceipts.size() > MAX_TRANSACTIONS) throw new IllegalStateException("Witness capacity exceeded");
            Map<String, Receipt> prepared = new LinkedHashMap<>();
            Map<String, String> outcomes = new HashMap<>();
            Path log = root.resolve("transactions.log");
            long maximumPrepared = 0;
            if (Files.exists(log)) {
                if (Files.size(log) > MAX_BYTES || Files.isSymbolicLink(log)) throw new IllegalStateException("Witness log capacity/identity failure");
                try (BufferedReader reader = Files.newBufferedReader(log, StandardCharsets.UTF_8)) {
                    for (String line; (line = reader.readLine()) != null;) {
                        String[] fields = line.split("\\|", -1);
                        if (fields.length != 6) throw new IllegalStateException("Malformed witness record");
                        long sequence = Long.parseLong(fields[0]); UUID.fromString(fields[1]);
                        String content = String.join("|", java.util.Arrays.copyOf(fields, 5));
                        if (!Hashes.same(chain, fields[4]) || !Hashes.same(Hashes.sha256(content), fields[5]) || !fields[3].matches("[0-9a-f]{64}")) {
                            throw new IllegalStateException("Witness chain failure");
                        }
                        chain = fields[5];
                        if (fields[2].equals("P")) {
                            if (sequence != maximumPrepared + 1 || prepared.containsKey(fields[1])) throw new IllegalStateException("Witness sequence failure");
                            maximumPrepared = sequence; prepared.put(fields[1], new Receipt(sequence, fields[3]));
                        } else {
                            Receipt receipt = prepared.get(fields[1]);
                            if (receipt == null || receipt.sequence != sequence || !Hashes.same(receipt.digest, fields[3]) || !fields[2].matches("[CAU]")) {
                                throw new IllegalStateException("Unbound outcome");
                            }
                            String previous = outcomes.get(fields[1]);
                            if (previous != null && !previous.equals("U")) throw new IllegalStateException("Final witness overwritten");
                            outcomes.put(fields[1], fields[2]);
                        }
                    }
                }
            } else if (!databaseReceipts.isEmpty() || lastSequence != 0) {
                throw new IllegalStateException("Missing witness for committed state");
            }
            journal = FileChannel.open(log, StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND);
            long maximumCommitted = 0;
            for (var entry : prepared.entrySet()) {
                String id = entry.getKey(); Receipt receipt = entry.getValue(); Receipt db = databaseReceipts.remove(id); String outcome = outcomes.get(id);
                if ("A".equals(outcome)) {
                    if (db != null) throw new IllegalStateException("Aborted witness has a committed receipt");
                    continue;
                }
                if (db == null || !db.equals(receipt)) throw new IllegalStateException("Committed/uncertain witness missing exact database receipt");
                maximumCommitted = Math.max(maximumCommitted, receipt.sequence);
                if (!"C".equals(outcome)) append(receipt.sequence, id, "C", receipt.digest);
            }
            if (!databaseReceipts.isEmpty() || maximumCommitted != lastSequence) throw new IllegalStateException("Unwitnessed database state or old snapshot");
            nextSequence = maximumPrepared + 1;
            lastCommittedSequence = maximumCommitted;
            reconcileSchema(connection,freshBootstrap);
            state = "READY"; reason = "RECONCILED";
        } catch (SQLException error) {
            state = "WAITING_DEPENDENCY"; reason = "DATABASE_UNAVAILABLE";
        } catch (Exception error) {
            state = "NOT_RECONCILED"; reason = error.getClass().getSimpleName();
        }
    }

    private String schemaHash(Connection connection) throws SQLException {
        StringBuilder rows=new StringBuilder();
        try (PreparedStatement query=connection.prepareStatement("SELECT CONCAT_WS('|',installed_rank,COALESCE(version,''),description,type,script,COALESCE(checksum,''),IF(success,1,0)) FROM flyway_schema_history ORDER BY installed_rank");ResultSet result=query.executeQuery()) {
            while(result.next())rows.append(result.getString(1)).append('\n');
        }
        return Hashes.sha256(rows.toString());
    }
    private void durableNew(Path path,String value) throws IOException {
        try(FileChannel output=FileChannel.open(path,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)) {
            ByteBuffer bytes=StandardCharsets.UTF_8.encode(value);
            while(bytes.hasRemaining())output.write(bytes);output.force(true);
        }
    }
    private void reconcileSchema(Connection connection,boolean freshBootstrap) throws Exception {
        Path expected=root.resolve("schema-history.sha256");Path pending=root.resolve("schema-migration.pending");
        if(Files.exists(pending))throw new IllegalStateException("Incomplete schema migration; independent reconciliation required");
        String actual=schemaHash(connection);
        if(freshBootstrap)durableNew(expected,actual+"\n");
        if(!Files.isRegularFile(expected) || Files.isSymbolicLink(expected) || !Hashes.same(Files.readString(expected).trim(),actual))
            throw new IllegalStateException("Schema witness mismatch");
        Flyway flyway=Flyway.configure().dataSource(database).locations("classpath:db/migration/"+service).cleanDisabled(true).load();
        // Compare independent history BEFORE any migration can change a restored database.
        if(flyway.info().pending().length>0) {
            durableNew(pending,generation+"|"+source+"|"+actual+"\n");
            flyway.migrate();
            String after=schemaHash(connection);Path replacement=root.resolve("schema-history-"+UUID.randomUUID()+".next");
            durableNew(replacement,after+"\n");
            Files.move(replacement,expected,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            Files.move(pending,root.resolve("schema-migration-"+UUID.randomUUID()+".completed"));
        }
        flyway.validate();
    }

    public synchronized <T> T write(String descriptor, SqlWork<T> operation) {
        if (!state.equals("READY")) throw new IllegalStateException("NOT_RECONCILED");
        long sequence = nextSequence++; String id = UUID.randomUUID().toString(); String digest = Hashes.sha256(descriptor);
        try { append(sequence, id, "P", digest); }
        catch (IOException error) { state = "NOT_RECONCILED"; reason = "WITNESS_UNAVAILABLE"; throw new IllegalStateException(reason, error); }
        boolean commitIssued = false;
        Connection connection;
        try { connection = database.getConnection(); }
        catch (SQLException connectionError) {
            try { append(sequence, id, "A", digest); }
            catch (IOException witnessError) { state = "NOT_RECONCILED"; reason = "WITNESS_UNAVAILABLE"; connectionError.addSuppressed(witnessError); }
            throw new IllegalStateException("Database unavailable", connectionError);
        }
        try {
            connection.setAutoCommit(false);
            try {
                // Also fence an in-place restore while this process is still alive.
                try (PreparedStatement query = connection.prepareStatement("SELECT generation,last_committed_seq FROM foundation_meta WHERE singleton=1 FOR UPDATE"); ResultSet rows = query.executeQuery()) {
                    if (!rows.next() || !Hashes.same(generation, rows.getString(1)) || rows.getLong(2) != lastCommittedSequence) {
                        state = "NOT_RECONCILED"; reason = "DATABASE_MARKER_MISMATCH";
                        throw new IllegalStateException(reason);
                    }
                }
                T result = operation.execute(connection);
                try (PreparedStatement insert = connection.prepareStatement("INSERT INTO tx_receipts(tx_id,sequence_no,payload_sha256) VALUES(?,?,?)")) {
                    insert.setString(1, id); insert.setLong(2, sequence); insert.setString(3, digest); insert.executeUpdate();
                }
                try (PreparedStatement update = connection.prepareStatement("UPDATE foundation_meta SET last_committed_seq=? WHERE singleton=1 AND generation=?")) {
                    update.setLong(1, sequence); update.setString(2, generation);
                    if (update.executeUpdate() != 1) throw new IllegalStateException("Generation changed during write");
                }
                commitIssued = true; connection.commit();
                append(sequence, id, "C", digest);
                lastCommittedSequence = sequence;
                return result;
            } catch (Exception error) {
                if (commitIssued) {
                    state = "NOT_RECONCILED"; reason = "COMMIT_UNKNOWN";
                    try { append(sequence, id, "U", digest); } catch (IOException witnessError) { error.addSuppressed(witnessError); }
                    throw new CommitUnknownException(id, error);
                }
                boolean rollbackConfirmed=true;
                try { connection.rollback(); append(sequence, id, "A", digest); }
                catch (Exception rollbackError) { rollbackConfirmed=false;state = "NOT_RECONCILED"; reason = "ROLLBACK_UNKNOWN"; error.addSuppressed(rollbackError); }
                if(rollbackConfirmed && error instanceof RuntimeException runtime)throw runtime;
                throw new IllegalStateException("Transaction rejected", error);
            }
        } catch (SQLException beginError) {
            try { connection.rollback(); append(sequence, id, "A", digest); }
            catch (Exception rollbackError) { state = "NOT_RECONCILED"; reason = "ROLLBACK_UNKNOWN"; beginError.addSuppressed(rollbackError); }
            throw new IllegalStateException("Cannot begin transaction", beginError);
        } finally {
            try { connection.close(); }
            catch (SQLException closeError) { state = "NOT_RECONCILED"; reason = "CONNECTION_CLOSE_FAILED"; }
        }
    }

    private void append(long sequence, String id, String outcome, String payload) throws IOException {
        if (journal == null || journal.size() >= MAX_BYTES || sequence > MAX_TRANSACTIONS) throw new IOException("Witness unavailable/capacity exhausted");
        String content = sequence + "|" + id + "|" + outcome + "|" + payload + "|" + chain;
        String digest = Hashes.sha256(content);
        ByteBuffer bytes = StandardCharsets.UTF_8.encode(content + "|" + digest + "\n");
        while (bytes.hasRemaining()) journal.write(bytes);
        journal.force(true); chain = digest;
    }
    public String state() { return state; }
    public String reason() { return reason; }
    public String generation() { return generation; }
    public boolean ready() { return state.equals("READY"); }
    public synchronized boolean verifyCurrent() {
        if (!ready()) return false;
        try (Connection connection = database.getConnection(); PreparedStatement query = connection.prepareStatement("SELECT generation,last_committed_seq FROM foundation_meta WHERE singleton=1"); ResultSet rows = query.executeQuery()) {
            if (!rows.next() || !Hashes.same(generation, rows.getString(1)) || rows.getLong(2) != lastCommittedSequence) {
                state = "NOT_RECONCILED"; reason = "DATABASE_MARKER_MISMATCH"; return false;
            }
            return true;
        } catch (SQLException error) { return false; }
    }
    public synchronized void block(String cause) { state = "NOT_RECONCILED"; reason = cause; }
    public synchronized void close() throws IOException {
        state = "STOPPED";
        if (journal != null) journal.close();
        processLock.release(); lockChannel.close();
    }
}
