package dev.guihong.mailbox.infrastructure;

import dev.guihong.mailbox.application.MailboxObjectStore;
import dev.guihong.platform.BlobRepository;
import java.util.UUID;

public final class PlatformMailboxObjectStore implements MailboxObjectStore {
    private final BlobRepository blobs;
    public PlatformMailboxObjectStore(BlobRepository blobs){this.blobs=blobs;}
    public Stored store(byte[] bytes,String authority,String kind,String referenceId){
        String id=UUID.randomUUID().toString();
        BlobRepository.Blob blob=blobs.stage(id,authority,bytes);
        try{blob=blobs.reference(id,kind,referenceId);}
        catch(RuntimeException failure){throw failure;}
        return new Stored(blob.id(),blob.sha256(),blob.size());
    }
    public byte[] read(String objectId){return blobs.read(objectId);}
    public void release(String objectId,String kind,String referenceId){blobs.dereference(objectId,kind,referenceId);}
}

