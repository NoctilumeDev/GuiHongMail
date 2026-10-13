package dev.guihong.mailbox.application;

public interface MailboxObjectStore {
    record Stored(String id,String sha256,long size) {}
    Stored store(byte[] bytes,String authority,String kind,String referenceId);
    byte[] read(String objectId);
    void release(String objectId,String kind,String referenceId);
}

