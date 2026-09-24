#!/usr/bin/env bash
# Optional: vendor official OIDF automation scripts next to our wrapper.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/runner/vendor"
BASE="${OIDF_SCRIPTS_BASE:-https://gitlab.com/openid/conformance-suite/-/raw/master/scripts}"
mkdir -p "${DEST}"
for file in run-test-plan.py conformance.py test_plan_parser.py; do
  echo "Fetching ${file}"
  curl -fsSL "${BASE}/${file}" -o "${DEST}/${file}"
done
echo "Official scripts saved to ${DEST}"
echo "Use: ./scripts/run-conformance.sh --component certify --official-script ${DEST}/run-test-plan.py"
