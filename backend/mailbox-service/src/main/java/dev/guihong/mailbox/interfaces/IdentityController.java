package dev.guihong.mailbox.interfaces;

import dev.guihong.mailbox.application.IdentityService;
import dev.guihong.mailbox.domain.Principal;
import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
public final class IdentityController {
    public record Login(String address,String password) {}
    public record Provision(String address,String password,String displayName) {}
    public record Enabled(boolean enabled) {}
    private final IdentityService identity;
    public IdentityController(IdentityService identity){this.identity=identity;}
    @Bean public FilterRegistrationBean<SessionFilter> sessions(){var bean=new FilterRegistrationBean<>(new SessionFilter(identity));bean.addUrlPatterns("/api/*");bean.setOrder(1);return bean;}
    @PostMapping("/api/auth/login") public ResponseEntity<?> login(@RequestBody Login login,HttpServletRequest request) {
        return session(identity.login(login.address,login.password,request.getRemoteAddr()));
    }
    @GetMapping("/api/auth/me") public Map<String,Object> me(HttpServletRequest request){return user((Principal)request.getAttribute("principal"));}
    @GetMapping("/api/accounts/{id}") public ResponseEntity<?> account(@PathVariable String id,HttpServletRequest request){
        Principal p=(Principal)request.getAttribute("principal");return p.accountId().equals(id)?ResponseEntity.ok(user(p)):ResponseEntity.status(404).body(Map.of("code","RESOURCE_NOT_FOUND"));
    }
    @PostMapping("/api/auth/refresh") public ResponseEntity<?> refresh(HttpServletRequest request){return session(identity.refresh((Principal)request.getAttribute("principal")));}
    @PostMapping("/api/auth/logout") public ResponseEntity<?> logout(HttpServletRequest request){identity.logout((Principal)request.getAttribute("principal"));return ResponseEntity.noContent().header(HttpHeaders.SET_COOKIE,cookie("",0)).build();}
    @PostMapping("/internal/accounts") public Map<String,Object> provision(@RequestBody Provision input){return Map.of("account_id",identity.provision(input.address,input.password,input.displayName));}
    @PostMapping("/internal/accounts/{id}/enabled") public ResponseEntity<?> enabled(@PathVariable String id,@RequestBody Enabled input){identity.enabled(id,input.enabled);return ResponseEntity.noContent().build();}
    private Map<String,Object> user(Principal p){return Map.of("account_id",p.accountId(),"address",p.address(),"display_name",p.displayName(),"role",p.role());}
    private String cookie(String value,long age){return ResponseCookie.from("guihong_session",value).httpOnly(true).sameSite("Strict").path("/api").maxAge(age).build().toString();}
    private ResponseEntity<?> session(IdentityService.Session s){return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE,cookie(s.token(),1800)).body(Map.of("user",user(s.principal()),"csrf",s.csrf()));}
}
