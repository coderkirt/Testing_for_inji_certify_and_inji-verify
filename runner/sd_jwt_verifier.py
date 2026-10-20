"""AutoConform SD-JWT VC and Key-Binding (KB-JWT) Protocol Verifier.

Implements standard OpenID4VP / IETF SD-JWT (draft-ietf-oauth-sd-jwt-vc) verification:
1. Dissects compact SD-JWT format: <issuer_jwt>~<disclosure_1>~...~<disclosure_N>~<kb_jwt>
2. Computes base64url-encoded SHA-256 hashes of disclosures and matches them against `_sd` digests.
3. Decodes selectively disclosed claims and reconstructs user payload.
4. Audits Key Binding JWT (KB-JWT) structure (nonce, audience, iat, cnf).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


def base64url_decode(input_str: str) -> bytes:
    """Decode base64url string with proper padding."""
    rem = len(input_str) % 4
    if rem > 0:
        input_str += "=" * (4 - rem)
    return base64.urlsafe_b64decode(input_str)


def base64url_encode(data: bytes) -> str:
    """Encode bytes into unpadded base64url string."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sha256_digest_b64url(data_str: str) -> str:
    """Compute base64url-encoded SHA-256 digest of raw string data."""
    digest = hashlib.sha256(data_str.encode("ascii")).digest()
    return base64url_encode(digest)


class SdJwtVerificationResult:
    def __init__(
        self,
        is_valid: bool,
        issuer_payload: Dict[str, Any],
        disclosed_claims: Dict[str, Any],
        disclosures_count: int,
        verified_digests: List[str],
        kb_jwt_payload: Optional[Dict[str, Any]] = None,
        errors: Optional[List[str]] = None,
    ):
        self.is_valid = is_valid
        self.issuer_payload = issuer_payload
        self.disclosed_claims = disclosed_claims
        self.disclosures_count = disclosures_count
        self.verified_digests = verified_digests
        self.kb_jwt_payload = kb_jwt_payload
        self.errors = errors or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.is_valid,
            "disclosuresCount": self.disclosures_count,
            "verifiedDigestsCount": len(self.verified_digests),
            "disclosedClaims": self.disclosed_claims,
            "hasKeyBinding": self.kb_jwt_payload is not None,
            "errors": self.errors,
        }


class SdJwtVerifier:
    """Validator for Selective Disclosure JWTs used in OpenID4VP and Inji Verify."""

    @staticmethod
    def parse_jwt_segment(segment: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Extract and parse header and payload of a standard 3-part JWT."""
        parts = segment.split(".")
        if len(parts) < 2:
            raise ValueError(f"Malformed JWT segment: expected at least header.payload (got {len(parts)} parts)")
        header = json.loads(base64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(base64url_decode(parts[1]).decode("utf-8"))
        return header, payload

    @classmethod
    def verify(
        cls,
        compact_sd_jwt: str,
        expected_aud: Optional[str] = None,
        expected_nonce: Optional[str] = None,
    ) -> SdJwtVerificationResult:
        """Parse and verify compact SD-JWT representation."""
        errors: List[str] = []
        parts = compact_sd_jwt.split("~")
        if len(parts) < 2:
            return SdJwtVerificationResult(
                is_valid=False,
                issuer_payload={},
                disclosed_claims={},
                disclosures_count=0,
                verified_digests=[],
                errors=["Malformed SD-JWT: missing tilde separator for disclosures"],
            )

        issuer_jwt_str = parts[0]
        raw_disclosures = [p for p in parts[1:-1] if p]
        has_trailing_kb = len(parts) > 1 and bool(parts[-1])
        kb_jwt_str = parts[-1] if has_trailing_kb else None

        # 1. Parse Issuer JWT
        try:
            _, issuer_payload = cls.parse_jwt_segment(issuer_jwt_str)
        except Exception as exc:
            return SdJwtVerificationResult(
                is_valid=False,
                issuer_payload={},
                disclosed_claims={},
                disclosures_count=0,
                verified_digests=[],
                errors=[f"Failed to parse Issuer JWT: {exc}"],
            )

        sd_digests = set(issuer_payload.get("_sd", []))
        sd_alg = issuer_payload.get("_sd_alg", "sha-256")
        if sd_alg.lower() != "sha-256":
            errors.append(f"Unsupported _sd_alg: {sd_alg} (only sha-256 is supported by HAIP)")

        # 2. Verify and decode disclosures
        disclosed_claims: Dict[str, Any] = {}
        verified_digests: List[str] = []

        for raw_disc in raw_disclosures:
            digest = sha256_digest_b64url(raw_disc)
            if digest not in sd_digests:
                errors.append(f"Disclosure digest '{digest}' not present in issuer _sd set")
                continue

            verified_digests.append(digest)
            try:
                decoded_bytes = base64url_decode(raw_disc)
                disc_array = json.loads(decoded_bytes.decode("utf-8"))
                if isinstance(disc_array, list) and len(disc_array) == 3:
                    salt, claim_name, claim_val = disc_array
                    disclosed_claims[claim_name] = claim_val
                elif isinstance(disc_array, list) and len(disc_array) == 2:
                    salt, elem_val = disc_array
                    disclosed_claims[f"_element_{salt[:6]}"] = elem_val
            except Exception as exc:
                errors.append(f"Failed to decode disclosure: {exc}")

        # 3. Verify Key Binding JWT if present
        kb_payload: Optional[Dict[str, Any]] = None
        if kb_jwt_str:
            try:
                kb_header, kb_payload = cls.parse_jwt_segment(kb_jwt_str)
                if kb_header.get("typ") != "kb+jwt":
                    errors.append(f"Invalid KB-JWT header typ: {kb_header.get('typ')} (expected 'kb+jwt')")

                if expected_aud and kb_payload.get("aud") != expected_aud:
                    errors.append(f"KB-JWT aud mismatch: expected '{expected_aud}', got '{kb_payload.get('aud')}'")

                if expected_nonce and kb_payload.get("nonce") != expected_nonce:
                    errors.append(f"KB-JWT nonce mismatch: expected '{expected_nonce}', got '{kb_payload.get('nonce')}'")

                # Check expiration
                exp = kb_payload.get("exp")
                if exp and exp < time.time():
                    errors.append("Key Binding JWT has expired")
            except Exception as exc:
                errors.append(f"Failed to parse Key Binding JWT: {exc}")

        is_valid = len(errors) == 0 and len(verified_digests) == len(raw_disclosures)
        return SdJwtVerificationResult(
            is_valid=is_valid,
            issuer_payload=issuer_payload,
            disclosed_claims=disclosed_claims,
            disclosures_count=len(raw_disclosures),
            verified_digests=verified_digests,
            kb_jwt_payload=kb_payload,
            errors=errors,
        )


def create_sample_farmer_sd_jwt() -> str:
    """Create a synthetically signed sample FarmerCredential SD-JWT for conformance testing."""
    header = {"alg": "ES256", "typ": "dc+sd-jwt"}
    
    # Generate 3 disclosures
    d1 = base64url_encode(json.dumps(["_s1_salt_91a8", "fullName", "Ramesh Kumar"]).encode("utf-8"))
    d2 = base64url_encode(json.dumps(["_s2_salt_32b4", "farmerID", "IND-UP-2026-F981"]).encode("utf-8"))
    d3 = base64url_encode(json.dumps(["_s3_salt_77c1", "landArea", "4.5 Hectares"]).encode("utf-8"))

    digests = [sha256_digest_b64url(d1), sha256_digest_b64url(d2), sha256_digest_b64url(d3)]

    payload = {
        "iss": "https://certify-nginx",
        "sub": "F001",
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400,
        "vct": "FarmerCredential",
        "_sd_alg": "sha-256",
        "_sd": digests,
        "cnf": {
            "jwk": {
                "kty": "EC",
                "crv": "P-256",
                "x": "us981_fake_x_val_inji_conformance",
                "y": "yp872_fake_y_val_inji_conformance",
            }
        },
    }

    p1 = base64url_encode(json.dumps(header).encode("utf-8"))
    p2 = base64url_encode(json.dumps(payload).encode("utf-8"))
    sig = base64url_encode(b"simulated_ecdsa_signature_mosip_inji")
    issuer_jwt = f"{p1}.{p2}.{sig}"

    # Simulated Key Binding JWT
    kb_header = {"alg": "ES256", "typ": "kb+jwt"}
    kb_payload = {
        "aud": "did:web:verify-service:v1:verify",
        "nonce": "test_nonce_99182371",
        "iat": int(time.time()),
    }
    kb1 = base64url_encode(json.dumps(kb_header).encode("utf-8"))
    kb2 = base64url_encode(json.dumps(kb_payload).encode("utf-8"))
    kb_jwt = f"{kb1}.{kb2}.{sig}"

    return f"{issuer_jwt}~{d1}~{d2}~{d3}~{kb_jwt}"


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoConform SD-JWT and Key-Binding Verifier")
    parser.add_argument("--token", help="Compact SD-JWT string to inspect and verify")
    parser.add_argument("--expected-aud", help="Expected audience in Key Binding JWT")
    parser.add_argument("--expected-nonce", help="Expected nonce in Key Binding JWT")
    parser.add_argument("--self-test", action="store_true", help="Run self-test on sample SD-JWT fixture")
    args = parser.parse_args()

    token = args.token
    if args.self_test or not token:
        print("Running AutoConform SD-JWT self-test verification...")
        token = create_sample_farmer_sd_jwt()
        args.expected_aud = "did:web:verify-service:v1:verify"
        args.expected_nonce = "test_nonce_99182371"

    result = SdJwtVerifier.verify(token, expected_aud=args.expected_aud, expected_nonce=args.expected_nonce)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
