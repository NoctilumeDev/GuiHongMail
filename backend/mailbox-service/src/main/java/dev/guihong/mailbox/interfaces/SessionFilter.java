package dev.guihong.mailbox.interfaces;

import dev.guihong.mailbox.application.IdentityService;
import dev.guihong.mailbox.domain.Principal;
import dev.guihong.platform.Hashes;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.web.filter.OncePerRequestFilter;

public final class SessionFilter extends OncePerRequestFilter {
    static final String ORIGIN="http://127.0.0.1:18080";
    private final IdentityService identity;
    public SessionFilter(IdentityService identity){this.identity=identity;}
    protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain) throws IOException,ServletException {
        response.setHeader("Cache-Control","no-store");
        String path=request.getRequestURI();boolean write=!request.getMethod().equals("GET") && !request.getMethod().equals("HEAD");
        if(write && !ORIGIN.equals(request.getHeader("Origin"))){reject(response,403,"ORIGIN_REJECTED");return;}
        if(path.equals("/api/auth/login")){chain.doFilter(request,response);return;}
        String token=null;
        if(request.getCookies()!=null)for(Cookie cookie:request.getCookies())if(cookie.getName().equals("guihong_session"))token=cookie.getValue();
        Principal principal;
        try{principal=identity.authenticate(token);}catch(RuntimeException unavailable){reject(response,503,"SERVICE_UNAVAILABLE");return;}
        if(principal==null){reject(response,401,"AUTHENTICATION_REQUIRED");return;}
        String csrf=request.getHeader("X-GuiHong-CSRF");
        if(write && (csrf==null || !Hashes.same(Hashes.sha256(csrf),principal.csrfHash()))){reject(response,403,"CSRF_REJECTED");return;}
        request.setAttribute("principal",principal);chain.doFilter(request,response);
    }
    private void reject(HttpServletResponse response,int status,String code) throws IOException {
        response.setStatus(status);response.setContentType("application/json;charset=UTF-8");response.getWriter().write("{\"code\":\""+code+"\"}");
    }
}
