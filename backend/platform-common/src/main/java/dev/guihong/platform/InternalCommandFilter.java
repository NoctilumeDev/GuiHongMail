package dev.guihong.platform;

import java.io.IOException;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/** Current foundation operator capability; user sessions grant no internal capability. */
public final class InternalCommandFilter implements Filter {
    private final FoundationSettings settings;
    public InternalCommandFilter(FoundationSettings settings) { this.settings=settings; }
    public void doFilter(ServletRequest request,ServletResponse response,FilterChain chain) throws IOException,ServletException {
        HttpServletRequest http=(HttpServletRequest)request;
        String caller=http.getHeader("X-GuiHong-Service");String bearer=http.getHeader("Authorization");
        if (!"lab".equals(caller) || bearer==null || !bearer.startsWith("Bearer ") || !Hashes.same(settings.internalToken(),bearer.substring(7))) {
            HttpServletResponse reply=(HttpServletResponse)response;reply.setStatus(401);reply.setContentType("application/json;charset=UTF-8");
            reply.getWriter().write("{\"code\":\"INTERNAL_AUTH_REQUIRED\"}");return;
        }
        chain.doFilter(request,response);
    }
}
