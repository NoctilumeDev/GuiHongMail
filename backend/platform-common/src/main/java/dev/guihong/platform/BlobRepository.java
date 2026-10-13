package dev.guihong.platform;

import java.net.ConnectException;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;

/** Technical object/ref registry confined to the current service's own credentials and generation. */
public final class BlobRepository {
    public record Blob(String id,String key,String sha256,long size,String state,int inFlight) {}
    private final WitnessGate witness;private final ObjectStore store;private final JdbcTemplate jdbc;private final WriteGate gate;
    public BlobRepository(WitnessGate witness,ObjectStore store,JdbcTemplate jdbc,WriteGate gate){
        this.witness=witness;this.store=store;this.jdbc=jdbc;this.gate=gate;reconcileReferences();
    }
    public synchronized boolean reconcileReferences(){
        gate.objectsReconciled(false);
        if(!witness.verifyCurrent() || !store.ready())return false;
        try{
            List<Blob> rows=jdbc.query("SELECT DISTINCT o.* FROM stored_objects o JOIN object_refs r ON r.object_id=o.object_id LIMIT 10001",(r,n)->new Blob(r.getString("object_id"),r.getString("object_key"),r.getString("sha256"),r.getLong("byte_size"),r.getString("lifecycle"),r.getInt("in_flight")));
            if(rows.size()>10000)throw new IllegalStateException("Object recovery capacity exceeded");
            for(Blob b:rows){if(!b.state.equals("LIVE") || !Hashes.same(b.sha256,Hashes.sha256(store.get(b.key))))throw new IllegalStateException("Object integrity mismatch");}
            gate.objectsReconciled(true);return true;
        }catch(RuntimeException unavailable){witness.block("OBJECTS_NOT_RECONCILED");return false;}
    }
    public Blob metadata(String id){UUID.fromString(id);return jdbc.queryForObject("SELECT * FROM stored_objects WHERE object_id=?",(r,n)->new Blob(r.getString("object_id"),r.getString("object_key"),r.getString("sha256"),r.getLong("byte_size"),r.getString("lifecycle"),r.getInt("in_flight")),id);}
    public synchronized Blob stage(String id,String authority,byte[] bytes){
        gate.requireWritable();UUID.fromString(id);
        if(authority==null || authority.length()>128 || authority.isBlank() || bytes.length>S3ObjectStore.MAX_BYTES)throw new IllegalArgumentException("Invalid object authority/size");
        String digest=Hashes.sha256(bytes),key="objects/"+witness.generation()+"/"+id;
        witness.write("object-stage|"+id+"|"+authority+"|"+digest,c->{
            try(var q=c.prepareStatement("INSERT INTO stored_objects(object_id,object_key,authority_key,sha256,byte_size,lifecycle,in_flight) VALUES(?,?,?,?,?,'STAGED',1)")){
                q.setString(1,id);q.setString(2,key);q.setString(3,authority);q.setString(4,digest);q.setLong(5,bytes.length);q.executeUpdate();
            }return null;
        });
        try{
            store.put(key,bytes);
            if(!Hashes.same(digest,Hashes.sha256(store.get(key))))throw new IllegalStateException("Staged object hash mismatch");
        }catch(RuntimeException failure){
            // With SDK retries disabled, connection refusal proves this PUT never reached a server.
            boolean notConnected=false;for(Throwable cause=failure;cause!=null;cause=cause.getCause())if(cause instanceof ConnectException)notConnected=true;
            if(notConnected && witness.verifyCurrent())orphan(id);
            // All other transport outcomes retain the stage and in-flight fence.
            throw failure;
        }
        return metadata(id);
    }
    public synchronized Blob reference(String id,String kind,String referenceId){
        gate.requireWritable();Blob blob=metadata(id);
        byte[] actual=store.get(blob.key);
        if(!Hashes.same(blob.sha256,Hashes.sha256(actual)))throw new IllegalStateException("Staged object hash mismatch");
        try{
            witness.write("object-reference|"+id+"|"+kind+"|"+referenceId+"|"+blob.sha256,c->{
                try(var q=c.prepareStatement("SELECT lifecycle FROM stored_objects WHERE object_id=? FOR UPDATE")){
                    q.setString(1,id);try(var rows=q.executeQuery()){if(!rows.next() || !List.of("STAGED","LIVE").contains(rows.getString(1)))throw new IllegalStateException("Object has no reference eligibility");}
                }
                try(var q=c.prepareStatement("INSERT INTO object_refs(ref_kind,ref_id,object_id) VALUES(?,?,?)")){q.setString(1,kind);q.setString(2,referenceId);q.setString(3,id);q.executeUpdate();}
                try(var q=c.prepareStatement("UPDATE stored_objects SET lifecycle='LIVE',in_flight=0 WHERE object_id=?")){q.setString(1,id);q.executeUpdate();}return null;
            });
        }catch(CommitUnknownException unknown){throw unknown;}
        catch(IllegalStateException rolledBack){if(witness.verifyCurrent() && blob.state.equals("STAGED"))orphan(id);throw rolledBack;}
        return metadata(id);
    }
    private void orphan(String id){witness.write("object-orphan|"+id,c->{
        try(var q=c.prepareStatement("UPDATE stored_objects SET lifecycle='ORPHAN',in_flight=0 WHERE object_id=? AND lifecycle='STAGED' AND NOT EXISTS(SELECT 1 FROM object_refs WHERE object_id=?)")){q.setString(1,id);q.setString(2,id);q.executeUpdate();}return null;
    });}
    public synchronized byte[] read(String id){
        gate.requireWritable();Blob blob=metadata(id);
        if(!blob.state.equals("LIVE"))throw new IllegalStateException("Object not confirmed");
        try{byte[] bytes=store.get(blob.key);if(!Hashes.same(blob.sha256,Hashes.sha256(bytes)))throw new IllegalStateException("Stored object hash mismatch");return bytes;}
        catch(RuntimeException failure){gate.objectsReconciled(false);witness.block("OBJECTS_NOT_RECONCILED");throw failure;}
    }
    public synchronized void dereference(String id,String kind,String referenceId){
        gate.requireWritable();witness.write("object-dereference|"+id+"|"+kind+"|"+referenceId,c->{
            try(var q=c.prepareStatement("DELETE FROM object_refs WHERE object_id=? AND ref_kind=? AND ref_id=?")){q.setString(1,id);q.setString(2,kind);q.setString(3,referenceId);q.executeUpdate();}
            try(var q=c.prepareStatement("UPDATE stored_objects SET lifecycle='ORPHAN' WHERE object_id=? AND lifecycle='LIVE' AND NOT EXISTS(SELECT 1 FROM object_refs WHERE object_id=?)")){q.setString(1,id);q.setString(2,id);q.executeUpdate();}return null;
        });
    }
    public synchronized List<String> gc(){
        gate.requireWritable();long deadline=System.nanoTime()+30_000_000_000L;
        List<Blob> candidates=jdbc.query("SELECT * FROM stored_objects o WHERE lifecycle IN('ORPHAN','DELETING') AND in_flight=0 AND created_at<DATE_SUB(NOW(6),INTERVAL 60 SECOND) AND NOT EXISTS(SELECT 1 FROM object_refs r WHERE r.object_id=o.object_id) ORDER BY created_at LIMIT 50",(r,n)->new Blob(r.getString("object_id"),r.getString("object_key"),r.getString("sha256"),r.getLong("byte_size"),r.getString("lifecycle"),r.getInt("in_flight")));
        List<String> deleted=new ArrayList<>();
        for(Blob b:candidates){
            if(System.nanoTime()>deadline)break;
            boolean claimed=witness.write("object-gc-claim|"+b.id,c->{try(var q=c.prepareStatement("UPDATE stored_objects SET lifecycle='DELETING' WHERE object_id=? AND lifecycle IN('ORPHAN','DELETING') AND in_flight=0 AND NOT EXISTS(SELECT 1 FROM object_refs WHERE object_id=?)")){q.setString(1,b.id);q.setString(2,b.id);return q.executeUpdate()==1;}});
            if(!claimed)continue;
            store.delete(b.key);
            witness.write("object-gc-complete|"+b.id,c->{try(var q=c.prepareStatement("UPDATE stored_objects SET lifecycle='DELETED' WHERE object_id=? AND lifecycle='DELETING' AND NOT EXISTS(SELECT 1 FROM object_refs WHERE object_id=?)")){q.setString(1,b.id);q.setString(2,b.id);if(q.executeUpdate()!=1)throw new IllegalStateException("GC state changed");}return null;});
            deleted.add(b.id);
        }
        return deleted;
    }
}
