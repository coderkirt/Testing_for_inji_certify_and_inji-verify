package io.mosip.certify.utils;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.mosip.certify.core.constants.ErrorConstants;
import io.mosip.certify.core.exception.CertifyException;
import io.mosip.certify.entity.IarSession;
import io.mosip.certify.security.DpopProofs;
import io.mosip.certify.services.KeyManagerConstants;
import io.mosip.kernel.signature.dto.JWSSignatureRequestDto;
import io.mosip.kernel.signature.dto.JWTSignatureResponseDto;
import io.mosip.kernel.signature.service.SignatureService;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.Instant;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;

@Component
public class AccessTokenJwtUtil {

    private static final Logger log = LoggerFactory.getLogger(AccessTokenJwtUtil.class);

    @Autowired
    private SignatureService signatureService;

    @Autowired
    private ObjectMapper objectMapper;

    @Value("${mosip.certify.cnonce-expire-seconds:300}")
    private int cNonceExpireSeconds;

    public String generateSignedJwt(IarSession session, String issuer, String audience, int expirySeconds) {
        String identityData = session.getIdentityData();
        if (!StringUtils.hasText(identityData)) {
            throw new CertifyException(ErrorConstants.INVALID_REQUEST, "Identity data is required but not found in session");
        }
        String scope = session.getScope();
        if (!StringUtils.hasText(scope)) {
            throw new CertifyException(ErrorConstants.INVALID_REQUEST, "Scope is required but not found in session");
        }
        return generateSignedJwt(identityData, scope, session.getClientId(), issuer, audience, expirySeconds);
    }

    public String generateSignedJwt(String identityData, String scope, String clientId,
                                     String issuer, String audience, int expirySeconds) {
        try {
            if (!StringUtils.hasText(identityData)) {
                throw new CertifyException(ErrorConstants.INVALID_REQUEST, "Identity data is required");
            }
            if (!StringUtils.hasText(scope)) {
                throw new CertifyException(ErrorConstants.INVALID_REQUEST, "Scope is required");
            }

            Instant now = Instant.now();
            long issuedAt = now.getEpochSecond();
            long expiresAt = issuedAt + expirySeconds;

            Map<String, Object> payload = new HashMap<>();
            payload.put("iss", issuer);
            payload.put("sub", identityData);
            payload.put("aud", audience);
            payload.put("iat", issuedAt);
            payload.put("exp", expiresAt);
            payload.put("client_id", clientId);
            payload.put("scope", scope);
            String dpopThumbprint = currentDpopThumbprint();
            if (dpopThumbprint != null) {
                payload.put("cnf", Map.of("jkt", dpopThumbprint));
            }

            String payloadJson = objectMapper.writeValueAsString(payload);
            String base64Payload = Base64.getUrlEncoder().withoutPadding().encodeToString(payloadJson.getBytes());

            JWSSignatureRequestDto signatureRequest = new JWSSignatureRequestDto();
            signatureRequest.setApplicationId(KeyManagerConstants.CERTIFY_SERVICE_APP_ID);
            signatureRequest.setReferenceId(KeyManagerConstants.EMPTY_REF_ID);
            signatureRequest.setDataToSign(base64Payload);
            signatureRequest.setIncludePayload(true);
            signatureRequest.setIncludeCertificate(false);
            signatureRequest.setIncludeCertHash(false);
            signatureRequest.setValidateJson(true);
            signatureRequest.setB64JWSHeaderParam(true);
            signatureRequest.setSignAlgorithm("RS256");

            JWTSignatureResponseDto response = signatureService.jwsSign(signatureRequest);
            return response.getJwtSignedData();
        } catch (CertifyException e) {
            throw e;
        } catch (Exception e) {
            log.error("Failed to generate signed JWT", e);
            throw new CertifyException(ErrorConstants.UNKNOWN_ERROR, "JWT generation failed", e);
        }
    }

    private static String currentDpopThumbprint() {
        if (!(RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attributes)) {
            return null;
        }
        HttpServletRequest request = attributes.getRequest();
        String dpop = request.getHeader("DPoP");
        if (dpop == null || dpop.isBlank()) {
            return null;
        }
        return DpopProofs.thumbprint(dpop);
    }
}
