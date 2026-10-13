package dev.guihong.platform;
import java.util.Base64;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
/** Authenticated lab commands; public user APIs never accept arbitrary object coordinates. */
@RestController
public final class BlobController {
    public record Stage(String objectId,String authority,String base64) {}
    public record Reference(String kind,String referenceId) {}
    private final BlobRepository blobs;
    public BlobController(BlobRepository blobs){this.blobs=blobs;}
    @PostMapping("/internal/storage/objects") public BlobRepository.Blob stage(@RequestBody Stage input){
        if(input.base64==null || input.base64.length()>7*1024*1024)throw new IllegalArgumentException("Payload size exceeded");
        return blobs.stage(input.objectId,input.authority,Base64.getDecoder().decode(input.base64));
    }
    @PostMapping("/internal/storage/objects/{id}/references") public BlobRepository.Blob reference(@PathVariable String id,@RequestBody Reference input){return blobs.reference(id,input.kind,input.referenceId);}
    @DeleteMapping("/internal/storage/objects/{id}/references") public ResponseEntity<?> dereference(@PathVariable String id,@RequestBody Reference input){blobs.dereference(id,input.kind,input.referenceId);return ResponseEntity.noContent().build();}
    @GetMapping("/internal/storage/objects/{id}") public ResponseEntity<byte[]> read(@PathVariable String id){return ResponseEntity.ok().contentType(MediaType.APPLICATION_OCTET_STREAM).body(blobs.read(id));}
    @PostMapping("/internal/storage/gc") public Map<String,Object> gc(){return Map.of("deleted",blobs.gc());}
    @ExceptionHandler(RuntimeException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("code","STORAGE_OPERATION_UNCONFIRMED"));}
}
