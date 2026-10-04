# Troubleshooting

## Suite never becomes ready

- Confirm `mongodb`, `server`, and `nginx` are up: `docker compose -f compose/docker-compose.yml ps`
- Open `https://localhost.emobix.co.uk:8443/` (accept the self-signed cert)
- On Windows, add `127.0.0.1 localhost.emobix.co.uk` to `C:\Windows\System32\drivers\etc\hosts`
- The runner uses `verify=False` for the local cert. Browsers still warn.

## Plan create fails with 400

- The suite image may not yet expose the 1.0 plan name. Check `GET /api/runner/available` and update `runner/configs/plans.json`.
- Variant keys must match what that suite build supports. Start from `issuer-variant.json` / `verifier-variant.json`.

## Certify or Verify not reachable from the suite

- Plan URLs must be Docker DNS names (`http://certify-nginx`, `http://verify-service:8080/v1/verify`), not `localhost`, when the runner is driving a compose stack.
- When pointing at a deployed env (api-testrig `ENV_ENDPOINT`), set `CERTIFY_ISSUER_URL` / `VERIFY_ENDPOINT` to the public URLs the suite container can route to.

## Postgres init failed

- First boot only runs `certify_init.sql` / `verify/init.sql`. Recreate volumes: `docker compose --env-file compose/.env -f compose/docker-compose.yml down -v`
- After changing `CERTIFY_IMAGE` (for example 0.14.0 to 1.0.0-alpha.1), recreate the `certify-pg` volume the same way. The 0.14 schema does not start 1.0.
- Certify 1.0 also needs `inji.keystore.file.path` (embedded inji-verify). The committed `certify-default.properties` sets it to `classpath:sample-keystore/test.p12`.
- `KER-KMA-004 No such alias` means `certify-pkcs12` and the keymanager tables are out of sync. Truncate `certify.key_alias` / `certify.key_store` or recreate both the PKCS12 volume and `certify-pg`. The PKCS12 volume is mounted at `/home/inji/CERTIFY_PKCS12` (Certify's working directory). After replacing `certify-service.jar` in a running container, keep that volume so keys stay aligned with Postgres.

## TestNG finds no modules

- `results/<mode>/results.json` is missing or the official script path was used without a mapper. Re-run without `--official-script`, or inspect the official export zip.

## Credential offer fails with `unknown_claims`

Certify 1.0 compares offer claims to `credential_metadata.claims` in `/.well-known/openid-credential-issuer`. For `dc+sd-jwt` FarmerCredential that list is empty, so any named claim is rejected. The runner sends `{}`.

## Credential endpoint HTTP 500

Suite 5.3.1 adds a random JSON field to the credential request, and its wallet proof sets `iss` to the static client id. Certify 1.0.0-alpha.1 rejects unknown JSON fields and rejects that `iss` because pre-authorized access tokens are minted with an empty `client_id`. After `compose up`, run `python scripts/patch-certify-ignore-unknown.py` and copy the patched JAR into the `certify` container. Restart `certify` after copying. The sources are `compose/certify/patch/CredentialRequest.java` and `compose/certify/patch/JwtProofValidator.java`.

Issuer plans must use `fapi_profile: vci` (not `plain_fapi`). `plain_fapi` skips credential-issuer metadata, so the suite sends `credential_configuration_id: null` and no proofs.

## All modules skipped but BUILD SUCCESS

- `expected-failures.json` remaps suite `FAILED` to TestNG skips. Certify issuer modules must not be listed there once the image is 1.0.
- `benchmark.json` `minPassRate` of `0.0` lets a zero-pass run stay green. The committed gate requires the seven unattended issuer modules.

## Result diff

```bash
python runner/result_diff.py --previous results/previous.json --current results/combined/results.json
```

Copy a good `results.json` to `results/previous.json` to compare the next CI run.
