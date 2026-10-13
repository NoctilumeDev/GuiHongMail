package dev.guihong.mailbox.interfaces;
import dev.guihong.mailbox.application.MailboxExceptions.*;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.http.converter.HttpMessageNotReadableException;
@RestControllerAdvice
public final class ApiErrors {
    @ExceptionHandler(IllegalArgumentException.class) public ResponseEntity<?> rejected(IllegalArgumentException error){
        String code="RATE_LIMITED".equals(error.getMessage())?"RATE_LIMITED":"AUTHENTICATION_FAILED";
        return ResponseEntity.status(code.equals("RATE_LIMITED")?429:401).body(Map.of("code",code));
    }
    @ExceptionHandler(InvalidInput.class) public ResponseEntity<?> invalid(InvalidInput error){return ResponseEntity.badRequest().body(Map.of("code",error.code()));}
    @ExceptionHandler(NotFound.class) public ResponseEntity<?> missing(){return ResponseEntity.status(404).body(Map.of("code","RESOURCE_NOT_FOUND"));}
    @ExceptionHandler(VersionConflict.class) public ResponseEntity<?> conflict(VersionConflict error){return ResponseEntity.status(409).body(Map.of("code","VERSION_CONFLICT","current_version",error.currentVersion()));}
    @ExceptionHandler(CommitOutcomeUnknown.class) public ResponseEntity<?> unknown(){return ResponseEntity.status(503).body(Map.of("code","COMMIT_OUTCOME_UNKNOWN"));}
    @ExceptionHandler({HttpMessageNotReadableException.class,MethodArgumentNotValidException.class,HttpMediaTypeNotSupportedException.class}) public ResponseEntity<?> malformed(){return ResponseEntity.badRequest().body(Map.of("code","REQUEST_MALFORMED"));}
    @ExceptionHandler(MaxUploadSizeExceededException.class) public ResponseEntity<?> upload(){return ResponseEntity.status(413).body(Map.of("code","ATTACHMENT_SIZE_EXCEEDED"));}
    @ExceptionHandler(IllegalStateException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("code","SERVICE_UNAVAILABLE"));}
}
