# Per-component handoff

Some OpenID4VP verifier modules wait for a wallet to complete a presentation. The suite goes to `WAITING` until the implementation (or a human) sends the OpenID4VP request to the suite's fake wallet.

## Inji Certify (issuer)

Most issuer metadata and pre-authorized-code modules are unattended. Authorization-code / HAIP variants may require a mocked authorization server. Keep those variants in `issuer-variant.json` only after Certify is configured for that grant.

If a module cannot run unattended, add it to `runner/configs/expected-skips.json`.

## Inji Verify (verifier)

When a module is `WAITING`:

1. The suite exports an `authorization_endpoint` URL for the current alias.
2. Point Verify at that URL instead of `openid4vp://` (same as a web wallet).
3. Or paste the `openid4vp://` link from Verify into the suite UI.

This harness automates only what the REST API can drive. Interactive wallet completion is documented here and skipped via `expected-skips.json` until a wallet stub is added.

For local mobile handoff, tunnel Verify (`ngrok` / similar) and replace `VERIFY_PUBLIC_HOST` so the wallet can reach the service. See the official Inji Verify compose README.

## Combined run

Combined mode runs both plans. Handoff skips on Verify do not fail the Certify gate. Unexpected Verify failures still fail the combined benchmark if `failOnUnexpectedFailure` is true.
