# Architecture

The harness is orchestration only. OpenID protocol logic stays in the OpenID Foundation conformance suite. MOSIP reporting stays in the existing TestNG / Extent api-testrig.

```
run-conformance.sh
        |
        +-- docker compose
        |     +-- OIDF suite (server, mongodb, nginx :8443)
        |     +-- Inji Certify (certify, certify-nginx, postgres)
        |     +-- Inji Verify (verify-service, verify-ui, postgres)
        |
        +-- runner/run_conformance.py
        |     +-- REST: POST /api/plan, POST /api/runner, GET /api/info, export
        |     +-- optional subprocess: official scripts/run-test-plan.py
        |     +-- writes results.json + HTML zip
        |
        +-- testrig-bridge OpenIDConformanceTest
              +-- one TestNG result per suite module
              +-- Extent Spark report
              +-- benchmark gate
```

## Run modes

- **Per-module (default):** Certify issuer plan is a Certify api-testrig suite. Verify verifier plan is a Verify api-testrig suite. Each gate is independent.
- **Combined:** both plans, one `results.json`, one Extent report, one badge-style summary.

## Network

All containers share `inji-openid-conformance`. The suite nginx service is aliased as `localhost.emobix.co.uk` so implementations can call back using the suite's advertised `BASE_URL`. The runner on the host talks to `https://localhost.emobix.co.uk:8443` (add that name to the host file). Plan JSON uses Docker DNS names (`http://certify-nginx`, `http://verify-service:8080/v1/verify`) because the suite process, not the host, calls the implementation.

## What this repo does not do

- It does not implement OpenID4VCI / OpenID4VP tests.
- It does not scrape the suite web UI.
- It does not replace mosip-functional-tests. It plugs into it.
