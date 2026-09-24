# How the API automation works

The OpenID Foundation documents the same REST flow used by `scripts/run-test-plan.py`:

1. Wait until `GET /api/plan?length=1` returns 200 (suite + Mongo are up). Local Docker needs no API token.
2. `POST /api/plan?planName=...&variant={...}` with the plan configuration JSON as the body.
3. `GET /api/plan/{id}` lists modules.
4. `POST /api/runner?test=MODULE&plan=PLAN_ID&variant={...}` starts a module.
5. Poll `GET /api/info/{testId}` until `status` is `FINISHED` or `INTERRUPTED`.
6. Export `GET /api/plan/exporthtml/{planId}` for the human-readable zip.

`runner/run_conformance.py` is a thin wrapper around that API. It:

- Selects issuer vs verifier from `runner/configs/plans.json`
- Renders `${CERTIFY_ISSUER_URL}` / `${VERIFY_ENDPOINT}` into the committed 1.0 templates
- Maps each module to `PASS` / `FAIL` / `SKIP`
- Honors `expected-failures.json` and `expected-skips.json`
- Evaluates `benchmark.json`
- Writes `results.json` for the Java bridge

To use the official script instead:

```bash
./scripts/bootstrap-official-scripts.sh
./scripts/run-conformance.sh --component certify \
  --official-script runner/vendor/run-test-plan.py
```

## Plan names (OpenID 1.0)

| Role | Plan | Variant file |
| --- | --- | --- |
| Inji Certify issuer | `oid4vci-1_0-issuer-test-plan` | `issuer-variant.json` |
| Inji Verify verifier | `oid4vp-1final-verifier-haip-test-plan` | `verifier-variant.json` |

Edit the JSON, do not click variants in the suite UI. Wrong variants look like product bugs.

## TestNG mapping

`OpenIDConformanceTest` reads `results.json` (or launches the runner). Each suite module becomes one TestNG method invocation. Expected failures and listed skips become `SkipException`. `BenchmarkGate` fails the suite if unexpected failures remain.
