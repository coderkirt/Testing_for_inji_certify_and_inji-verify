# How the API automation works

The runner drives the same REST surface the OpenID Foundation documents and
`scripts/run-test-plan.py` uses. Nothing here is a screen scrape: every step is a documented
call, so a suite upgrade shows up as a failing assertion rather than a broken click path.

## The flow

| Step | Call | Notes |
| --- | --- | --- |
| 1. Wait for the suite | `GET api/plan?length=1` until 200 | proves suite **and** Mongo are up; `--skip-wait` skips it |
| 2. Validate (optional) | `GET api/plan/available` | `--validate-plans`: are the plan name and every variant key offered by this build? |
| 3. Create the plan | `POST api/plan?planName={plan}&variant={json}` body = plan config | 201 expected; a rejection raises with the suite's own error text |
| 4. List modules | `GET api/plan/{id}` | falls back to the create response when it already lists modules |
| 5. Create a module | `POST api/runner?test={module}&plan={planId}&variant={json}` | one instance per module |
| 6. Start it if needed | `POST api/runner/{id}` | what `run-test-plan.py` does for modules that do not auto-start |
| 7. Poll | `GET api/info/{id}` every 3s | until terminal, handoff, or the module timeout |
| 8. Adjudicate | `GET api/log/{id}` | condition-level pass/fail, matched against the expected-failures schema |
| 9. Export | `GET api/plan/exporthtml/{id}`, `GET api/plan/export/{id}` | human-readable zip and signed JSON zip |

Local Docker needs no API token. A hosted suite does: pass `--token` or set
`CONFORMANCE_TOKEN`.

The client trusts the suite's self-signed certificate for local Docker
(`verify=False`). That is a local-stack concession, not a production posture.

## The module state machine

`wait_for_settled` collapses `api/info` status into exactly one outcome, and the mapping
from outcome to verdict is explicit:

| Suite state | Outcome | Mapped | Why |
| --- | --- | --- | --- |
| `FINISHED` | `FINISHED` | `PASSED` → `PASS`, `FAILED` → `FAIL` | normal path |
| `INTERRUPTED` | `INTERRUPTED` | `FAIL` | the suite stopped the module |
| `WAITING` | `WAITING` | `SKIP`, `handoff: true` | blocked on a wallet — see [handoff.md](handoff.md) |
| `CONFIGURED` (never started) | `CONFIGURED` | `SKIP` | auto-start was attempted and refused |
| past `--module-timeout` | `TIMEOUT` | `FAIL` | reported with the elapsed limit |
| anything that throws | `ERROR` | `FAIL` | with the exception text as `error` |

Result values are read from the same fields the official driver reads:
`PASSED`, `PASSED_WITH_WARNINGS`, `WARNING`, `REVIEW` are passes; `FAILED`, `FAILURE`,
`INTERRUPTED` are failures; `SKIPPED`, `SKIP`, `NOT_RUN` are skips. An empty result on a
finished module is a **FAIL**, not a silent pass.

Two rules keep parallelism honest. Modules inside a plan run in parallel with
`--parallel`, capped at 4 workers, **unless the plan config declares an `alias`** — the
suite cannot register one alias concurrently, so `run-test-plan.py` serialises in that
case and so does this runner (`--force-parallel-modules` overrides, if you know better).

## Condition-level adjudication

A module verdict alone is not enough: a module can report `PASSED` while individual
conformance conditions failed. `runner/conditions.py` ports the official adjudication —
build the block timeline from the log, then match each `FAILURE`/`WARNING` entry against
the expected failures and skips.

`runner/configs/expected-failures.json` accepts both granularities:

```jsonc
{
  "conditions": [                       // the OIDF run-test-plan.py schema
    {
      "test-name": "oid4vci-1_0-issuer-*", // shell wildcards allowed
      "configuration-filename": "issuer-plan.json",
      "variant": { "credential_format": "sd_jwt_vc" },  // "*" or a partial map
      "current-block": "Credential endpoint",
      "condition": "ValidateCredentialResponseSignature",
      "expected-result": "failure",       // "failure" or "warning"
      "comment": "tracked in ISSUE-123"
    }
  ],
  "modules": {                          // harness shorthand: skip the whole module
    "oid4vci-1_0-issuer-deferred-issuance": "no wallet stub yet"
  }
}
```

Consequences worth knowing:

- A module whose **every** failing condition is covered becomes a documented `SKIP`, not a
  `FAIL` — the module result and the condition log agree.
- A failure that is **not** covered stays a failure, even inside an otherwise passing
  module, and counts in `unexpectedFailures`.
- An expected failure that **does not happen** is counted in `expectedFailuresDidNotHappen`.
  With `failOnStaleExpectation: true` that fails the gate, so this file cannot rot.

## results.json

One document per run, written to `<output-dir>/results.json`. It is the single contract
between the runner, the TestNG bridge, the diff tool and the S3 publisher.

```jsonc
{
  "runId": "certify-1758700000",
  "mode": "certify",                 // certify | verify | combined
  "driver": "rest-api",              // or "run-test-plan.py" in official-script mode
  "startedAt": "...", "finishedAt": "...", "suiteUrl": "...",
  "endpoints": { "CERTIFY_ISSUER_URL": "http://certify-nginx", "...": "..." },
  "selection": { "only": [], "skip": [] },        // present only for a filtered run
  "plans": [
    {
      "component": "certify", "role": "issuer",
      "planName": "oid4vci-1_0-issuer-test-plan",
      "configFile": "issuer-plan.json",
      "planId": "...", "variant": { "...": "..." }, "alias": "...",
      "exportHtml": "results/certify/certify/<id>.zip",
      "exportJson": "results/certify/certify/<id>.json.zip",
      "modules": [
        {
          "testModule": "oid4vci-1_0-issuer-metadata",
          "key": "oid4vci-1_0-issuer-metadata[credential_format=sd_jwt_vc]",
          "component": "certify", "planName": "...", "configFile": "issuer-plan.json",
          "variant": { "...": "..." }, "testId": "...",
          "status": "FINISHED", "result": "PASSED",
          "mapped": "PASS",              // PASS | FAIL | SKIP - what TestNG reports
          "expectedFailure": false, "expectedSkip": false,
          "handoff": false, "filtered": false,
          "outcome": "FINISHED",         // FINISHED | INTERRUPTED | WAITING | CONFIGURED
                                         // | TIMEOUT | ERROR | FILTERED | EXPECTED_SKIP
          "reason": null, "error": null,
          "counts": { "SUCCESS": 12, "WARNING": 0, "FAILURE": 0 },
          "unexpectedFailures": [ { "current_block": "...", "src": "..." } ],
          "unexpectedWarnings": [], "expectedFailures": [],
          "expectedFailuresDidNotHappen": [], "unexpectedSkip": false
        }
      ]
    }
  ],
  "summary": { "passed": 9, "failed": 0, "skipped": 2, "gradedFailures": 0,
               "toleratedFailures": 1, "handoffSkips": 1, "filtered": 0,
               "ranModules": [], "passedModules": [], "failedModules": [],
               "skippedModules": [], "filteredModules": [],
               "adjudicatedModules": 9, "unexpectedFailures": 0,
               "unexpectedWarnings": 0, "unexpectedSkips": 0, "staleExpectations": 0,
               "errors": 0, "conditions": { "SUCCESS": 0, "WARNING": 0, "FAILURE": 0 } },
  "benchmarkMet": true,
  "benchmarkReasons": [],
  "benchmarkMetrics": { "passRate": 1.0, "conditionSuccessRate": 1.0, "...": "..." },
  "benchmarkChecks": [ { "name": "minPassRate", "ok": true, "detail": "..." } ],
  "diff": { "...": "..." }, "diffAgainst": "results/baseline.json"
}
```

`ranModules` deliberately excludes filtered modules, which is what makes
`requiredModules` a real check rather than a formality.

## Plan names and variants (OpenID 1.0)

| Role | Plan | Variant file |
| --- | --- | --- |
| Inji Certify issuer | `oid4vci-1_0-issuer-test-plan` | `runner/configs/issuer-variant.json` |
| Inji Verify verifier | `oid4vp-1final-verifier-haip-test-plan` | `runner/configs/verifier-variant.json` |

Edit the JSON, do not click variants in the suite UI — a variant chosen by hand is not
reproducible and a wrong variant looks exactly like a product bug. Run
`--validate-plans` after changing anything here; it reports variant dimensions this suite
build does not offer instead of letting plan create fail 40 seconds later.

## Driving the official script instead

`--official-script path/to/run-test-plan.py` shells out to the Foundation's own driver
(after `./scripts/bootstrap-official-scripts.sh`). It is supported for comparison, and it
is honest about its limits: the official script owns its own pass/fail logic and returns no
module list, so the bridge would see zero modules and report everything as skipped. That is
a false green, so **an official-script run fails the gate unless you pass
`--accept-official-exit-code`**, which opts into gating on the script's exit code alone.
See [troubleshooting.md](troubleshooting.md) for when that is the right trade.
