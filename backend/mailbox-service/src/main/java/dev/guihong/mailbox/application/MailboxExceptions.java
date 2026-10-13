package dev.guihong.mailbox.application;

public final class MailboxExceptions {
    private MailboxExceptions() {}
    public static final class NotFound extends RuntimeException {}
    public static final class VersionConflict extends RuntimeException {
        private final long currentVersion;
        public VersionConflict(long currentVersion){super("VERSION_CONFLICT");this.currentVersion=currentVersion;}
        public long currentVersion(){return currentVersion;}
    }
    public static final class InvalidInput extends RuntimeException {
        private final String code;
        public InvalidInput(String code){super(code);this.code=code;}
        public String code(){return code;}
    }
    public static final class CommitOutcomeUnknown extends RuntimeException {
        public CommitOutcomeUnknown(Throwable cause){super("COMMIT_OUTCOME_UNKNOWN",cause);}
    }
}

