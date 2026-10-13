package dev.guihong.platform;

public final class CommitUnknownException extends RuntimeException {
    private final String transactionId;
    public CommitUnknownException(String id, Throwable cause) {
        super("Transaction outcome must be reconciled", cause); transactionId = id;
    }
    public String transactionId() { return transactionId; }
}
