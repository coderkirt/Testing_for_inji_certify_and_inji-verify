package io.mosip.certify.security;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSVerifier;
import com.nimbusds.jose.crypto.ECDSAVerifier;
import com.nimbusds.jose.crypto.Ed25519Verifier;
import com.nimbusds.jose.crypto.RSASSAVerifier;
import com.nimbusds.jose.jwk.JWK;
import com.nimbusds.jwt.JWT;
import com.nimbusds.jwt.JWTParser;
import com.nimbusds.jwt.SignedJWT;
import jakarta.servlet.http.HttpServletRequest;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.Map;

/**
 * Binds a DPoP proof to the access token confirmation key.
 */
public final class DpopProofs {
    private DpopProofs() {
    }

    public static String accessToken(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        if (header == null) {
            return null;
        }
        int space = header.indexOf(' ');
        if (space < 0 || space == header.length() - 1) {
            return null;
        }
        return header.substring(space + 1).trim();
    }

    public static String thumbprint(String dpopJwt) {
        try {
            JWK jwk = SignedJWT.parse(dpopJwt).getHeader().getJWK();
            if (jwk == null || jwk.isPrivate()) {
                return null;
            }
            return jwk.computeThumbprint().toString();
        } catch (Exception ex) {
            return null;
        }
    }

    public static boolean binds(String dpopJwt, String accessToken) {
        try {
            SignedJWT proof = SignedJWT.parse(dpopJwt);
            JWK jwk = proof.getHeader().getJWK();
            if (jwk == null || jwk.isPrivate() || !verify(proof, jwk)) {
                return false;
            }
            JWT access = JWTParser.parse(accessToken);
            Object confirmation = access.getJWTClaimsSet().getClaim("cnf");
            if (!(confirmation instanceof Map<?, ?> cnf)) {
                return false;
            }
            if (!jwk.computeThumbprint().toString().equals(cnf.get("jkt"))) {
                return false;
            }
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(accessToken.getBytes(StandardCharsets.US_ASCII));
            String expectedAth = Base64.getUrlEncoder().withoutPadding().encodeToString(hash);
            return expectedAth.equals(proof.getJWTClaimsSet().getStringClaim("ath"));
        } catch (Exception ex) {
            return false;
        }
    }

    private static boolean verify(SignedJWT proof, JWK jwk) throws Exception {
        JWSAlgorithm algorithm = proof.getHeader().getAlgorithm();
        JWSVerifier verifier;
        if (JWSAlgorithm.ES256.equals(algorithm) || JWSAlgorithm.ES384.equals(algorithm) || JWSAlgorithm.ES512.equals(algorithm)) {
            verifier = new ECDSAVerifier(jwk.toECKey());
        } else if (JWSAlgorithm.EdDSA.equals(algorithm)) {
            verifier = new Ed25519Verifier(jwk.toOctetKeyPair());
        } else if (JWSAlgorithm.RS256.equals(algorithm) || JWSAlgorithm.PS256.equals(algorithm)) {
            verifier = new RSASSAVerifier(jwk.toRSAKey());
        } else {
            return false;
        }
        return proof.verify(verifier);
    }
}
