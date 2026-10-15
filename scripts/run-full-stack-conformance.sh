#!/usr/bin/env bash
# Deliverable alias for the combined Certify + Verify run.
# Pass --skip-compose when the stack is already up and Certify must not be recreated.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ROOT}/scripts/run-conformance.sh" --combined "$@"
