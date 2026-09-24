# Automated Conformance Testing for Inji Certify and Inji Verify

Standalone harness that spins up **Inji Certify**, **Inji Verify**, and a local **OpenID Foundation conformance suite**, drives the suite REST API (the same flow as `run-test-plan.py`), and feeds each plan into the existing TestNG / Extent **api-testrig** as one suite per module — plus an optional combined run.

This repo does **not** implement OpenID protocol tests. It orchestrates the official suite and maps results.

## One command

```bash
# Git Bash / WSL / Linux / macOS
./scripts/run-conformance.sh --component certify
./scripts/run-conformance.sh --component verify
./scripts/run-conformance.sh --combined

# Windows PowerShell
.\scripts\run-conformance.ps1 -Component certify
.\scripts\run-conformance.ps1 -Combined
```

`scripts/run-full-stack-conformance.sh` is the combined-run alias.

Each path: compose up → wait healthy → create/run/poll plans → `results.json` → TestNG/Extent → fail on benchmark regression.

## Prerequisites

- Docker + Docker Compose
- Python 3.10+ (`pip install -r runner/requirements.txt`)
- Java 11+ and Maven (for the TestNG bridge)
- Hosts entry: `127.0.0.1 localhost.emobix.co.uk`

Copy `compose/.env.example` to `compose/.env` before the first run.

## Layout

| Path | Role |
| --- | --- |
| [compose/](compose/) | OIDF suite + Inji Certify 1.0 + Inji Verify 1.0 |
| [runner/](runner/) | REST wrapper, 1.0 plan JSON, expected-failures, benchmark, result diff |
| [testrig-bridge/](testrig-bridge/) | `OpenIDConformanceTest` per module + combined suite |
| [scripts/run-conformance.sh](scripts/run-conformance.sh) | One-command entry |
| [.github/workflows/full-stack-conformance.yml](.github/workflows/full-stack-conformance.yml) | CI |

## Docs

- [Architecture](docs/architecture.md)
- [API automation](docs/api-automation.md)
- [Per-component handoff](docs/handoff.md)
- [Self-certification](docs/self-certification.md)
- [Troubleshooting](docs/troubleshooting.md)
- [api-testrig drop-in](testrig-bridge/README.md)

## Point at an existing env

Same contract as api-testrig:

```bash
export ENV_ENDPOINT=https://certify.example.org
export VERIFY_ENDPOINT=https://verify.example.org/v1/verify
./scripts/run-conformance.sh --component certify --skip-compose
```

## Expected failures and diffs

- Edit `runner/configs/expected-failures.json` for known product gaps (they become TestNG skips, not silent greens).
- Edit `runner/configs/expected-skips.json` for interactive OpenID4VP modules.
- `runner/configs/benchmark.json` fails the build if unexpected failures remain.
- Compare runs: `python runner/result_diff.py --previous results/previous.json --current results/combined/results.json`

## Parallel execution

`--parallel` runs Certify and Verify plans together on a combined run, and starts suite modules concurrently (capped) inside each plan.
