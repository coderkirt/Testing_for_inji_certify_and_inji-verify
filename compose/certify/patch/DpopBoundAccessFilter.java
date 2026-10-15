package io.mosip.certify.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Rejects a credential request whose DPoP proof is not bound to the access token.
 * OID4VCI multiple-client tests present another client's key and expect 4xx.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
// Credential calls that present DPoP must match the access token. Other paths are unchanged.
public class DpopBoundAccessFilter extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String path = request.getRequestURI();
        String dpop = request.getHeader("DPoP");
        if (path == null || !path.contains("/issuance/credential") || dpop == null || dpop.isBlank()) {
            filterChain.doFilter(request, response);
            return;
        }
        String accessToken = DpopProofs.accessToken(request);
        if (accessToken == null || !DpopProofs.binds(dpop, accessToken)) {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            response.setContentType("application/json");
            response.getWriter().write("{\"error\":\"invalid_token\"}");
            return;
        }
        filterChain.doFilter(request, response);
    }
}
