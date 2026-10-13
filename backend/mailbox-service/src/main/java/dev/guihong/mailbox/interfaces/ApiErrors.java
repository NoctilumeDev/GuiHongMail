package dev.guihong.mailbox.interfaces;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
@RestControllerAdvice
public final class ApiErrors {
    @ExceptionHandler(IllegalArgumentException.class) public ResponseEntity<?> rejected(IllegalArgumentException error){
        String code="RATE_LIMITED".equals(error.getMessage())?"RATE_LIMITED":"AUTHENTICATION_FAILED";
        return ResponseEntity.status(code.equals("RATE_LIMITED")?429:401).body(Map.of("code",code));
    }
    @ExceptionHandler(IllegalStateException.class) public ResponseEntity<?> unavailable(){return ResponseEntity.status(503).body(Map.of("code","SERVICE_UNAVAILABLE"));}
}
