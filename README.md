# Automated Conformance Testing for Inji Certify and Inji Verify

Runs the **OpenID Foundation conformance suite** against **Inji Certify** (OpenID4VCI 1.0
issuer) and **Inji Verify** (OpenID4VP 1.0 verifier), and maps every conformance module
into the MOSIP **api-testrig** TestNG / Extent reporting the two products already use.

This repository does not implement OpenID protocol tests and does not scrape the suite
UI. It brings the stack up, drives the suite's REST API the way the official
`run-test-plan.py` does, adjudicates the result, gates it against a benchmark, and
publishes the report.

```
./scripts/run-conformance.sh --component certify     # issuer plan  -> results/certify
./scripts/run-conformance.sh --component verify      # verifier plan -> results/verify
./scripts/run-conformance.sh --combined              # both, one report -> results/combined
```

`scripts/run-full-stack-conformance.sh` is the combined-run alias. On Windows use
`.\scripts\run-conformance.ps1 -Component certify` (or `-Combined`).

Each run does the same five things: bring the stack up and wait for real health, create
and configure the plan, run every module, adjudicate the suite log, then map the result
into TestNG/Extent and gate on the benchmark.

## Prerequisites

| Need | Why |
| --- | --- |
| Docker + Docker Compose v2 | the stack (`docker compose version` must work) |
| Python 3.10+ | the runner; `pip install -r runner/requirements.txt` |
| Java 11 + Maven | the TestNG/Extent bridge |
| `127.0.0.1 localhost.emobix.co.uk` in your hosts file | the suite publishes that hostname |

Copy `compose/.env.example` to `compose/.env` before the first run — the entry points do
it for you if you forget. The default `.env` pins the 1.0 image line for both products
and needs no edits for a local run.

## Run modes and flags

| Command | What it proves |
| --- | --- |
| `--component certify` | the issuer plan, as one Certify api-testrig suite |
| `--component verify` | the verifier plan, as one Verify api-testrig suite |
| `--combined` | both plans, one `results.json`, one Extent report, one gate |

Useful flags (full list in [runner/README.md](runner/README.md)):

```bash
--parallel                  # overlap the two plans, and modules inside a plan when safe
--validate-plans            # check plan names + variant keys against the live suite, then exit
--only '*issuer-metadata*'  # selective execution: everything else is reported as a filtered skip
--skip '*deferred*'         # never drive these modules
--diff-against results/previous.json   # compare module by module
--baseline results/baseline.json       # benchmark against a stored good run
--save-baseline             # store this run as the next baseline after it passes
--publish-reports           # push reports to the api-testrig S3/MinIO bucket
--fail-fast / --module-timeout 300 / --no-auto-start
```

Selective execution never hides anything: a module that was not selected is still listed
in `results.json` and in the report as a **filtered skip**, and a filtered module cannot
satisfy `requiredModules` in the benchmark.

## Where the results land

| Artifact | Path |
| --- | --- |
| Machine-readable run result | `results/<mode>/results.json` |
| Suite HTML export (human readable) | `results/<mode>/<component>/*.zip` |
| Signed suite JSON export | `results/<mode>/<component>/*.json.zip` |
| TestNG results | `testrig-bridge/target/surefire-reports/` |
| Extent Spark report | `testrig-bridge/target/extent/OpenIDConformance-<mode>.html` |
| Benchmark baseline (opt-in) | `results/baseline.json` |
| api-testrig bucket (opt-in) | `s3://automationtests/<prefix>/<run-id>/...` |

`results.json` carries a per-module verdict plus the evidence behind it: suite status and
result, the mapped `PASS`/`FAIL`/`SKIP`, whether it was an expected failure, an expected
skip or a wallet handoff, the condition counts, and any unexpected failure or warning
with its conformance block. Nothing in the report is a guess.

## The gate

The gate is `runner/configs/benchmark.json`, evaluated by `runner/benchmark.py` and
surfaced in TestNG by `BenchmarkGate`. The key rule: **rates are computed over modules
that actually produced a verdict**, so declaring a known gap or hitting a documented
wallet handoff cannot move the pass rate — only a real regression can.

```jsonc
{
  "minPassRate": 1.0,              // passed / (passed + failed - tolerated)
  "failOnUnexpectedFailure": true, // condition-level failures count, not just module ones
  "failOnStaleExpectation": true,  // an expected-failure rule that stopped firing is a failure
  "failOnHandoff": false,          // wallet handoffs are a known limitation
  "requiredModules": [],           // modules that must produce a verdict
  "minConditionSuccessRate": 0.0,  // per-condition floor, from api/log/{id}
  "failOnRegression": false,       // needs --baseline / --diff-against
  "baselineFile": null
}
```

Known product gaps live in `runner/configs/expected-failures.json` (module level, or
condition level using the OIDF schema) and deliberate skips in
`runner/configs/expected-skips.json`. Both make a module a *documented skip* rather than
a silent green, and both are checked for staleness.

Compare two runs directly:

```bash
python runner/result_diff.py --previous results/previous.json --current results/combined/results.json
```

## Layout

| Path | Role |
| --- | --- |
| [compose/](compose/) | OIDF suite + Inji Certify 1.0 + Inji Verify 1.0 on one network |
| [runner/](runner/) | REST driver, condition adjudication, benchmark, diff, S3 publish |
| [testrig-bridge/](testrig-bridge/) | `OpenIDConformanceTest` per module + the combined suite |
| [scripts/](scripts/) | one-command entry points (bash and PowerShell) |
| [.github/workflows/full-stack-conformance.yml](.github/workflows/full-stack-conformance.yml) | CI: runner tests, then the real stack |

## Docs

- [Architecture](docs/architecture.md) — how the pieces fit and what is deliberately not automated
- [API automation](docs/api-automation.md) — the REST flow, the state machine, the `results.json` contract
- [Per-component handoff](docs/handoff.md) — `WAITING` modules and the wallet problem
- [Self-certification](docs/self-certification.md) — from local gate to an OpenID submission
- [Troubleshooting](docs/troubleshooting.md) — the failures you will actually hit
- [api-testrig drop-in](testrig-bridge/README.md) — wiring this into `mosip-functional-tests`

## Point at an existing environment

Same contract as the api-testrig: it uses `ENV_ENDPOINT` when it is set.

```bash
export ENV_ENDPOINT=https://certify.example.org
export VERIFY_ENDPOINT=https://verify.example.org/v1/verify
./scripts/run-conformance.sh --component certify --skip-compose
```

With `--skip-compose` the runner no longer owns the stack, so give it URLs the *suite*
container can reach — the suite, not your shell, calls the implementation.

## CI

`.github/workflows/full-stack-conformance.yml` runs two tiers:

1. **`runner-tests`** on every push and PR — `pytest runner/tests`, `bash -n` on the entry
   points, and `mvn test` for the bridge. No Docker, about a minute, and it is the tier
   that catches a bridge that does not compile.
2. **`conformance`** on non-PR events — a matrix over `certify`/`verify`, restores the
   cached baseline for that component, runs the full stack with `--parallel
   --save-baseline`, uploads `results/` and both reports, and optionally publishes to S3
   when the `PUSH_REPORTS_TO_S3` secret is set. `--combined` is a manual
   `workflow_dispatch` option.
