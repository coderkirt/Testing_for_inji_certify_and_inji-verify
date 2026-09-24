# Conformance runner

The Python driver. It owns the conversation with the OpenID Foundation suite's REST API and
writes the single artifact everything else consumes — `results.json`.

```bash
pip install -r runner/requirements.txt

python runner/run_conformance.py --component certify  --output-dir results/certify
python runner/run_conformance.py --component verify   --output-dir results/verify
python runner/run_conformance.py --combined --parallel --output-dir results/combined
python runner/run_conformance.py --component certify --validate-plans    # check configs against the live suite
```

Or use the entry point, which also brings the stack up, health-checks it and runs the
TestNG bridge: `./scripts/run-conformance.sh --component certify`.

Dependencies are deliberately thin — `httpx` plus the standard library. The S3 publisher
signs its own requests rather than pulling in the AWS SDK.

## Flags

| Flag | Effect |
| --- | --- |
| `--component certify\|verify` / `--combined` | required; what to run |
| `--suite-url URL` | suite base URL (default `CONFORMANCE_SERVER` or `https://localhost.emobix.co.uk:8443/`) |
| `--token TOKEN` | bearer token for a hosted suite |
| `--certify-issuer-url URL` | issuer URL the suite calls (`CERTIFY_ISSUER_URL`, else `ENV_ENDPOINT`) |
| `--verify-endpoint URL` | verifier API the suite calls |
| `--credential-configuration-id ID` | credential configuration the issuer plan requests |
| `--output-dir DIR` | where `results.json` and the exports go (default `results`) |
| `--expected-failures FILE` | override `configs/expected-failures.json` |
| `--expected-skips FILE` | override `configs/expected-skips.json` |
| `--benchmark FILE` | override `configs/benchmark.json` |
| `--diff-against FILE` | diff this run against a stored `results.json` and record it in the document |
| `--baseline FILE` | benchmark baseline (falls back to `benchmark.json` → `baselineFile`) |
| `--only PATTERN` / `--skip PATTERN` | selective execution; repeatable and comma separated, matched against the module name and its `name[k=v]` key |
| `--parallel` | run the two plans concurrently, and modules within a plan where the suite allows |
| `--force-parallel-modules` | parallel modules even when the plan config declares an `alias` |
| `--auto-start` / `--no-auto-start` | explicitly start modules sitting in `CONFIGURED` (default: on) |
| `--handoff-grace SECS` | keep polling a `WAITING` module this long before recording a handoff skip |
| `--module-timeout SECS` | per-module budget (default 600, or `OIDF_MODULE_TIMEOUT`) |
| `--no-condition-analysis` | skip `api/log/{id}` adjudication (module verdicts only) |
| `--fail-fast` | stop a plan after its first failure |
| `--skip-wait` | do not wait for the suite to become ready |
| `--validate-plans` | print whether the suite offers the configured plans and variant keys, then exit |
| `--official-script PATH` | shell out to the Foundation's `run-test-plan.py` instead of the REST driver |
| `--accept-official-exit-code` | gate on the official script's exit code; without it that mode fails by design |

Environment equivalents: `CONFORMANCE_SERVER`, `CONFORMANCE_TOKEN`, `CERTIFY_ISSUER_URL`,
`ENV_ENDPOINT`, `VERIFY_ENDPOINT`, `CERTIFY_CREDENTIAL_CONFIGURATION_ID`,
`OIDF_MODULE_TIMEOUT`, `OIDF_HANDOFF_GRACE`.

## Outputs

| File | Contents |
| --- | --- |
| `<output-dir>/results.json` | the run document: every module's verdict plus its evidence |
| `<output-dir>/<component>/<planId>.zip` | the suite's human-readable HTML export |
| `<output-dir>/<component>/<planId>.json.zip` | the suite's signed JSON export |
| `<output-dir>/<component>-plan.rendered.json` | the exact plan config that was used (official-script mode) |

Exit code `0` means the benchmark was met, `1` means it was not (or the run could not be
driven). Either way `results.json` is authoritative and is written whenever a plan ran.

## Config files

| File | Role |
| --- | --- |
| `configs/plans.json` | component → plan name, variant file, plan config |
| `configs/issuer-plan.json`, `configs/verifier-plan.json` | plan config templates with `${...}` placeholders |
| `configs/issuer-variant.json`, `configs/verifier-variant.json` | the consumed variants (1.0) |
| `configs/benchmark.json` | the gate |
| `configs/expected-failures.json`, `configs/expected-skips.json` | declared gaps and deliberate skips |
| `configs/s3.json` | report publishing, same keys as the api-testrig |

Placeholders available in plan templates: `${CERTIFY_ISSUER_URL}`, `${VERIFY_ENDPOINT}`,
`${CERTIFY_CREDENTIAL_CONFIGURATION_ID}`, `${ENV_ENDPOINT}`; any other `${NAME}` is resolved
from the environment or left as-is.

## The benchmark model

`benchmark.py` computes two rates and a set of checks. The important property: **rates are
computed over modules that produced a verdict**, in the numerator and the denominator, so a
declared gap or a documented handoff never moves the pass rate.

```
passRate            = passed / (passed + failed - toleratedFailures)
conditionSuccessRate = SUCCESS / (SUCCESS + WARNING + FAILURE)   # from api/log/{id}
```

| Key | Default | Meaning |
| --- | --- | --- |
| `minPassRate` | `1.0` | floor for `passRate` |
| `failOnUnexpectedFailure` | `true` | any failure not covered by expected-failures fails, including condition-level ones inside a `PASSED` module |
| `failOnUnexpectedWarning` / `maxUnexpectedWarnings` | `false` / `0` | warnings are counted and reported even when tolerated |
| `failOnUnexpectedSkip` / `maxUnexpectedSkips` | `false` / `0` | same, for skips that were not declared |
| `failOnStaleExpectation` | `true` | an expected failure that did not happen fails the run, so the file cannot rot |
| `failOnHandoff` | `false` | set `true` to insist everything ran unattended |
| `requiredModules` | `[]` | modules that must be graded; a filtered-out or skipped one fails the run |
| `minConditionSuccessRate` | `0.0` | per-condition floor, off by default |
| `failOnRegression` | `false` | needs `--baseline`/`--diff-against`; fails on PASS→FAIL and PASS→SKIP |
| `baselineFile` | `null` | default baseline, resolved relative to `configs/` |

Console output is one line per check (`[ok]` / `[FAIL]`) plus the metrics, and the same data
lands in `benchmarkChecks`/`benchmarkMetrics` in `results.json` so a failure is actionable
from the artifact alone.

## Declaring known failures

Module level, or condition level using the OIDF schema — both may be used, see
[../docs/api-automation.md](../docs/api-automation.md) for the full example. In short:

```jsonc
// expected-failures.json
{
  "conditions": [ { "test-name": "...", "configuration-filename": "issuer-plan.json",
                    "variant": { "credential_format": "sd_jwt_vc" },
                    "current-block": "...", "condition": "...",
                    "expected-result": "failure", "comment": "ISSUE-123" } ],
  "modules": { "module-name": "reason" }        // never started, reported as a skip
}
// expected-skips.json
{ "conditions": [], "modules": ["module-name"] }
```

A module whose failing conditions are **all** covered becomes a documented `SKIP`; anything
else stays a failure. That is the point of porting the official schema rather than keeping a
list of module names.

## Selective execution

```bash
python runner/run_conformance.py --component certify --only '*issuer-metadata*'
python runner/run_conformance.py --component certify --skip '*deferred*,*happy-flow*'
```

Unselected modules are **not** dropped from the report: they are listed with
`mapped: "SKIP"`, `filtered: true`, `outcome: "FILTERED"` and the matching pattern as the
reason, and `summary.ranModules` excludes them so `requiredModules` still means something.
The run document records the filter under `selection`.

## Publishing reports

`runner/s3_upload.py` writes to the same bucket the MOSIP api-testrig uses
(`apitest-commons/S3Adapter.java`), with the same config keys:

| Key | Notes |
| --- | --- |
| `push-reports-to-s3` | master switch; off by default |
| `s3-host` | MinIO or S3-compatible endpoint (omit for AWS S3) |
| `s3-region` | also part of the SigV4 scope |
| `s3-user-key` / `s3-user-secret` | credentials (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` also accepted) |
| `s3-account` | bucket, default `automationtests` |
| `reportExpirationInDays` | retention metadata |
| `s3-prefix` | object prefix, default `conformance` |

Precedence is CLI flag → `configs/s3.json` → environment, so CI can override everything with
secrets. Objects land at `<prefix>/<run-id>/<path relative to --source>`.

```bash
python runner/s3_upload.py --source results --run-id "$GITHUB_RUN_ID" --dry-run   # preview keys
./scripts/run-conformance.sh --component certify --publish-reports
```

A publish failure is reported and never masks the conformance result.

## Diffing two runs

```bash
python runner/result_diff.py --previous results/previous.json --current results/combined/results.json
```

Reports added/removed modules, verdict changes by rank (`PASS` > `SKIP` > `FAIL`), and
regressions — including `PASS`→`SKIP`, because a module that stopped running is a
regression even though nothing turned red. `--diff-against` folds the same structure into
`results.json` under `diff`, which is what `failOnRegression` evaluates.

## Tests

```bash
python -m pytest runner/tests -q      # 122 tests, no Docker, no network
```

They are not a formality: `tests/test_end_to_end.py` starts a stub conformance suite over
real HTTP and drives the real `main()` through it, which is how the handoff, condition and
benchmark regressions above are pinned. `tests/fixtures/results-with-expected-failures.json`
is also read by the Java `ResultMapperTest`, so the two languages are tested against one
shared contract.

## Official script mode

```bash
./scripts/bootstrap-official-scripts.sh          # vendors run-test-plan.py + helpers into runner/vendor/
./scripts/run-conformance.sh --component certify \
    --official-script runner/vendor/run-test-plan.py
```

Useful to compare behaviour, but the official driver returns no module list, so the bridge
would see zero modules and call everything a skip. That is a false green, so this mode fails
the gate unless you pass `--accept-official-exit-code` and accept gating on the exit code
alone.
