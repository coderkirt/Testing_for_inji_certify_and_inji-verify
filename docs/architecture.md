# Architecture

The harness is orchestration only. OpenID protocol logic stays in the OpenID Foundation
conformance suite; MOSIP reporting stays in the api-testrig TestNG / Extent stack. This
repository is the glue, and it is deliberately thin: one Python driver, one TestNG class
per module, one compose file.

```
scripts/run-conformance.sh --component certify|verify|--combined
        |
        +-- docker compose up -d --wait            (health-gated, not "sleep 20")
        |     +-- mongodb, server, nginx           OIDF suite (:8443, alias localhost.emobix.co.uk)
        |     +-- certify-db, certify, certify-nginx
        |     +-- verify-db, verify-service, verify-ui
        |
        +-- HTTP health checks on the host: suite, /.well-known/openid-credential-issuer,
        |   /v1/verify/actuator/health
        |
        +-- runner/run_conformance.py              (REST driver)
        |     +-- POST api/plan                  create + configure the plan
        |     +-- POST api/runner, POST api/runner/{id}
        |     +-- GET  api/info/{id}             poll to a terminal state
        |     +-- GET  api/log/{id}              adjudicate conditions
        |     +-- GET  api/plan/export{,html}/{planId}
        |     +-- writes results.json + the suite exports
        |     +-- evaluates benchmark.json -> exit code
        |
        +-- mvn -Pconformance-suite test           (TestNG bridge)
        |     +-- ResultMapper: results.json -> one ModuleResult per module
        |     +-- OpenIDConformanceTest: one TestNG result per module
        |     +-- ExtentReportListener: target/extent/OpenIDConformance-<mode>.html
        |     +-- BenchmarkGate: @AfterSuite fails the build if the benchmark is not met
        |
        +-- runner/s3_upload.py                    (opt-in, api-testrig bucket)
```

## Design rules

These are the rules the original version of this harness broke, and they are the reason
the tests exist.

1. **A module can never abort the run.** Every module is executed inside its own guard.
   A transport error, a suite 500, a timeout or a worker crash becomes a `FAIL` with an
   `error` string. The plan still exports and the report still gets written.
2. **A handoff is not a hang.** Some OpenID4VP modules legitimately park in `WAITING`
   until a wallet completes the presentation. That is recorded as a documented `SKIP`
   (`handoff: true`) instead of burning the module timeout and killing the plan.
3. **The condition log is the truth.** A module can report `PASSED` while emitting failing
   conditions. Conditions are adjudicated from `api/log/{id}` using the same expected-failure
   schema as `run-test-plan.py`, so "green" means green at condition level too.
4. **Known gaps are declared, not hidden.** `expected-failures.json` turns a known gap into
   a skip with a reason, and a rule that stops firing is itself a failure so the file
   cannot rot.
5. **Rates are computed over what was graded.** Modules that were skipped by design are
   excluded from the pass rate, in the numerator and the denominator. Declaring a gap
   never moves the number, so the gate and the expected-failures file cannot cancel out.
6. **A partial run must not look complete.** Selective execution reports unselected
   modules as filtered skips, and a filtered module cannot satisfy `requiredModules`.

## Run modes

- **Per-module (default).** The Certify issuer plan is one Certify api-testrig suite; the
  Verify verifier plan is one Verify api-testrig suite. Each is an independent gate, so a
  verifier regression never reds out the issuer, and the two can run as separate CI jobs.
- **Combined.** Both plans in one `results.json`, one Extent report, one summary. Used for
  the cross-module view and for the combined CI job.

## Plan creation and configuration

`runner/configs/plans.json` maps each component to a plan name, a variant file and a
plan-config template. The templates contain `${CERTIFY_ISSUER_URL}`,
`${VERIFY_ENDPOINT}` and `${CERTIFY_CREDENTIAL_CONFIGURATION_ID}` placeholders;
`config_render.py` substitutes them from the CLI/environment so the same template works
against the compose stack and against a deployed environment. The rendered config is what
gets `POST`ed to `api/plan?planName=...&variant=...`.

Variants are data, not UI clicks, and both the plan name and the variant keys can be
verified against the running suite with `--validate-plans` before anything runs.

## Network

All containers share the `inji-openid-conformance` network. The suite's nginx service is
aliased `localhost.emobix.co.uk` so an implementation can call back to the suite's
advertised `BASE_URL`. The runner talks to `https://localhost.emobix.co.uk:8443` from the
host, which is why the hosts-file entry is a hard prerequisite — and why the client
currently accepts the suite's self-signed certificate.

Plan URLs use Docker DNS names (`http://certify-nginx`,
`http://verify-service:8080/v1/verify`) because the **suite container**, not the host,
calls the implementation. Pointing a plan at `localhost` makes the suite call itself.

## Failure modes that are loud on purpose

| Symptom | What happens |
| --- | --- |
| A service crash-loops | `docker compose up --wait` fails before a single module runs |
| Certify/Verify not answering | the entry point waits on real endpoints and fails with the URL |
| Plan name or variant not offered by this suite build | `--validate-plans` reports it; otherwise plan create fails with the suite's own error text |
| Module never finishes | `FAIL` with the elapsed timeout, and the rest of the plan still runs |
| Module parks in `WAITING` | documented handoff skip, with the `docs/handoff.md` pointer in the reason |
| Module never auto-started | started explicitly (`--auto-start`), reported as `CONFIGURED` only if that fails |
| Benchmark regresses | non-zero runner exit, and `BenchmarkGate` fails the TestNG suite |
| Report publish fails | logged, but never masks the run result |

## What this repository does not do

- It does not implement OpenID4VCI / OpenID4VP test logic.
- It does not automate an interactive wallet: `WAITING` modules are skipped and documented.
- It does not replace `mosip-functional-tests`; it plugs into it (see
  [testrig-bridge/README.md](../testrig-bridge/README.md)).
- It does not substitute for a paid OpenID certification submission against the hosted
  suite (see [self-certification.md](self-certification.md)).
