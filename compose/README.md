# Compose stack

One network, three participants, no external dependencies: the OpenID Foundation's prebuilt
conformance suite, Inji Certify as the OpenID4VCI 1.0 issuer, and Inji Verify as the
OpenID4VP 1.0 verifier.

```bash
cp compose/.env.example compose/.env
docker compose --env-file compose/.env -f compose/docker-compose.yml up -d --wait
```

`--wait` is the point: every service with a healthcheck must report healthy before the
command returns, so a crash-looping container fails here instead of surfacing later as a
batch of confusing conformance failures. The entry points use the same command.

## Services

| Service | Image | Ports | Notes |
| --- | --- | --- | --- |
| `server` | `registry.gitlab.com/openid/conformance-suite:latest` | — | suite API; waits on `mongodb` |
| `nginx` | `.../conformance-suite/nginx:latest` | `8443` | aliased `localhost.emobix.co.uk` |
| `mongodb` | `mongo:6.0.13` | — | suite datastore, healthchecked with `ping` |
| `certify` | `injistack/inji-certify-with-plugins:1.0.0-alpha.1` | `8090` | issuer, profile `default,csvdp-farmer`, healthchecked on actuator |
| `certify-nginx` | `nginx:stable` | `8091` | `/.well-known/*` entry point the suite calls |
| `certify-db` | `postgres:15` | `5433` | seeded from `certify/certify_init.sql` |
| `verify-service` | `injistack/inji-verify-service:latest` | `8080` | verifier API, healthchecked on actuator |
| `verify-ui` | `injistack/inji-verify-ui:latest` | `3000` | optional demo UI, mounts `verify/config.json` |
| `verify-db` | `postgres:13` | `5432` | seeded from `verify/init.sql` |

All of them share the `inji-openid-conformance` bridge network. The nginx service carries the
`localhost.emobix.co.uk` alias so the suite is reachable at the URL it advertises, and
Certify/Verify carry `extra_hosts: localhost.emobix.co.uk:host-gateway` so they can call the
suite back — which is what a callback-based flow needs.

## Hosts file

The suite publishes `https://localhost.emobix.co.uk:8443`, so the host must resolve it:

```
127.0.0.1 localhost.emobix.co.uk
```

`/etc/hosts`, or `C:\Windows\System32\drivers\etc\hosts` on Windows. Browsers will still
warn about the self-signed certificate; the runner accepts it for local runs.

## Pinned images

The 1.0 line is what the plans target, so that is what is pinned:

- `CERTIFY_IMAGE=injistack/inji-certify-with-plugins:1.0.0-alpha.1` — the current 1.0 tag
  for this repository on Docker Hub.
- `VERIFY_IMAGE=injistack/inji-verify-service:latest` — `latest` resolves to the 1.0.0-alpha
  line; pin the explicit tag once you have confirmed which one you are testing.
- `IMAGE_TAG=latest` for the suite itself.

`.env.example` also documents the fallback `0.14.x` Certify tag next to `CERTIFY_IMAGE`. It
exists because the vendored `certify_init.sql` seed was taken from that generation: if a 1.0
image refuses to boot against the seeded database, switch the pin and record why. Anything
you change must be reflected in `.env.example` too, so a fresh clone is reproducible.

## The `.env` keys that matter

| Key | Why |
| --- | --- |
| `CERTIFY_ISSUER_URL` | the URL the harness gives the suite as `vci.credential_issuer_url` |
| `CERTIFY_ISSUER_PUBLIC_URL` | the issuer identity Certify advertises — **keep the two identical**, or the suite reports metadata mismatches |
| `CERTIFY_CREDENTIAL_CONFIGURATION_ID` | credential configuration the issuer plan requests (seeded by `certify_init.sql`) |
| `VERIFY_ENDPOINT` | verifier API the suite calls (`http://verify-service:8080/v1/verify`) |
| `VERIFY_PUBLIC_HOST` | hostname Verify uses to call back into the suite or a wallet; set a tunnel host for a real wallet handoff |
| `*_PORT` | host side port mappings; the entry points read them for their health checks |
| `PUSH_REPORTS_TO_S3` + `S3_*` | report publishing, same keys as the api-testrig |
| `HEALTH_TIMEOUT` | how long `up --wait` may take (entry-point side, default 600s) |

## Certify as its own authorization server

MOSIP's stock `certify-default.properties` points the authorization and token endpoints at
`https://esignet-mock.collab.mosip.net` — an external mock. A run that depends on an external
service is not a reproducible CI gate, and the harness also used to reference a
`mock-identity-system:8082` container that this compose file never started.

The compose file now overrides the exact properties the upstream file documents for
"use certify as your own authorization server":

```
mosip_certify_domain_url
mosip_certify_authorization_url
mosip_certify_authn_issuer_uri
mosip_certify_authn_jwk_set_uri
```

All four default to `${CERTIFY_ISSUER_PUBLIC_URL}`, so the stack is self-contained: nothing
outside this compose file is required for an unattended run. The vendored
`certify-csvdp-farmer.properties` carries a comment pointing at the same override so the two
cannot drift apart silently.

## Selective start

```bash
# suite only
docker compose -f compose/docker-compose.yml up -d --wait mongodb server nginx

# suite + issuer
docker compose ... up -d --wait mongodb server nginx certify-db certify certify-nginx

# suite + verifier
docker compose ... up -d --wait mongodb server nginx verify-db verify-service verify-ui
```

The entry points do exactly this based on `--component`, so a certify run never pulls the
Verify images.

## Resetting state

First boot only runs the SQL seeds, so schema or seed changes need fresh volumes:

```bash
docker compose -f compose/docker-compose.yml down -v
```

The Certify issuer serves its `/.well-known/openid-credential-issuer` through
`certify-nginx` (both the bare path and the path-suffixed `/v1/certify` variant the suite
expects when the issuer URL carries a path), which is what the health check and the suite
both probe.
