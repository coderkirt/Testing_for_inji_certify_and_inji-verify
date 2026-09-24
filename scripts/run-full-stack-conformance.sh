#!/usr/bin/env bash
# Deliverable alias for the combined Certify + Verify run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ROOT}/scripts/run-conformance.sh" --combined "$@"
