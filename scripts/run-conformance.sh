#!/usr/bin/env bash
# One-command conformance harness.
#   ./scripts/run-conformance.sh --component certify
#   ./scripts/run-conformance.sh --component verify
#   ./scripts/run-conformance.sh --combined
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT}/compose/docker-compose.yml"
ENV_FILE="${ROOT}/compose/.env"
COMPONENT=""
COMBINED=0
SKIP_COMPOSE=0
SKIP_TESTRIG=0
PARALLEL=0
OFFICIAL_SCRIPT=""
DIFF_AGAINST=""
EXTRA_RUNNER_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  run-conformance.sh --component certify|verify [--skip-compose] [--skip-testrig] [--parallel]
  run-conformance.sh --combined [--skip-compose] [--skip-testrig] [--parallel]

Environment:
  CONFORMANCE_SERVER   default https://localhost.emobix.co.uk:8443/
  CERTIFY_ISSUER_URL   issuer URL the suite will call (docker DNS or host)
  VERIFY_ENDPOINT      verifier API the suite will call
  ENV_ENDPOINT         api-testrig endpoint; used as CERTIFY_ISSUER_URL when set
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --component)
      COMPONENT="${2:-}"
      shift 2
      ;;
    --combined)
      COMBINED=1
      shift
      ;;
    --skip-compose)
      SKIP_COMPOSE=1
      shift
      ;;
    --skip-testrig)
      SKIP_TESTRIG=1
      shift
      ;;
    --parallel)
      PARALLEL=1
      shift
      ;;
    --official-script)
      OFFICIAL_SCRIPT="${2:-}"
      shift 2
      ;;
    --diff-against)
      DIFF_AGAINST="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      EXTRA_RUNNER_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ "${COMBINED}" -eq 0 && -z "${COMPONENT}" ]]; then
  usage
  exit 2
fi
if [[ "${COMBINED}" -eq 0 && "${COMPONENT}" != "certify" && "${COMPONENT}" != "verify" ]]; then
  echo "component must be certify or verify" >&2
  exit 2
fi

MODE="combined"
if [[ "${COMBINED}" -eq 0 ]]; then
  MODE="${COMPONENT}"
fi

if [[ ! -f "${ENV_FILE}" && -f "${ROOT}/compose/.env.example" ]]; then
  cp "${ROOT}/compose/.env.example" "${ENV_FILE}"
fi

compose() {
  if [[ -f "${ENV_FILE}" ]]; then
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
  else
    docker compose -f "${COMPOSE_FILE}" "$@"
  fi
}

start_stack() {
  local services=(mongodb server nginx)
  if [[ "${MODE}" == "combined" || "${MODE}" == "certify" ]]; then
    services+=(certify-db certify certify-nginx)
  fi
  if [[ "${MODE}" == "combined" || "${MODE}" == "verify" ]]; then
    services+=(verify-db verify-service verify-ui)
  fi
  echo "Starting services: ${services[*]}"
  compose up -d "${services[@]}"
}

wait_http() {
  local url="$1"
  local name="$2"
  local attempts="${3:-40}"
  echo "Waiting for ${name} at ${url}"
  for ((i = 1; i <= attempts; i++)); do
    if curl -kfsS "${url}" >/dev/null 2>&1; then
      echo "${name} is up"
      return 0
    fi
    sleep 5
  done
  echo "Timed out waiting for ${name}" >&2
  return 1
}

if [[ "${SKIP_COMPOSE}" -eq 0 ]]; then
  start_stack
  wait_http "${CONFORMANCE_SERVER:-https://localhost.emobix.co.uk:8443/}" "OpenID conformance suite" 48 || true
fi

export CONFORMANCE_SERVER="${CONFORMANCE_SERVER:-https://localhost.emobix.co.uk:8443/}"
if [[ -n "${ENV_ENDPOINT:-}" && -z "${CERTIFY_ISSUER_URL:-}" ]]; then
  export CERTIFY_ISSUER_URL="${ENV_ENDPOINT}"
fi
export CERTIFY_ISSUER_URL="${CERTIFY_ISSUER_URL:-http://certify-nginx}"
export VERIFY_ENDPOINT="${VERIFY_ENDPOINT:-http://verify-service:8080/v1/verify}"

OUT_DIR="${ROOT}/results/${MODE}"
mkdir -p "${OUT_DIR}"

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

RUNNER_CMD=("${PYTHON_BIN}" "${ROOT}/runner/run_conformance.py" --output-dir "${OUT_DIR}" --suite-url "${CONFORMANCE_SERVER}")
if [[ "${COMBINED}" -eq 1 ]]; then
  RUNNER_CMD+=(--combined)
else
  RUNNER_CMD+=(--component "${COMPONENT}")
fi
if [[ "${PARALLEL}" -eq 1 ]]; then
  RUNNER_CMD+=(--parallel)
fi
if [[ -n "${OFFICIAL_SCRIPT}" ]]; then
  RUNNER_CMD+=(--official-script "${OFFICIAL_SCRIPT}")
fi
if [[ -n "${DIFF_AGAINST}" ]]; then
  RUNNER_CMD+=(--diff-against "${DIFF_AGAINST}")
fi
if [[ ${#EXTRA_RUNNER_ARGS[@]} -gt 0 ]]; then
  RUNNER_CMD+=("${EXTRA_RUNNER_ARGS[@]}")
fi

echo "Running ${MODE} conformance"
set +e
"${RUNNER_CMD[@]}"
RUNNER_EXIT=$?
set -e
if [[ "${RUNNER_EXIT}" -ne 0 ]]; then
  echo "Conformance runner failed with exit code ${RUNNER_EXIT}" >&2
  exit "${RUNNER_EXIT}"
fi

if [[ "${SKIP_TESTRIG}" -eq 0 ]]; then
  SUITE_XML="src/test/resources/testng-${MODE}.xml"
  echo "Mapping results into TestNG suite ${SUITE_XML}"
  mvn -f "${ROOT}/testrig-bridge/pom.xml" -Pconformance-suite test \
    -DsuiteXmlFile="${SUITE_XML}" \
    -Dconformance.results="${OUT_DIR}/results.json" \
    -Dconformance.component="${MODE}" \
    -Dconformance.reuseResults=true \
    -Dconformance.repoRoot="${ROOT}"
fi

if [[ -f "${OUT_DIR}/results.json" && -f "${ROOT}/results/previous.json" && -z "${DIFF_AGAINST}" ]]; then
  "${PYTHON_BIN}" "${ROOT}/runner/result_diff.py" \
    --previous "${ROOT}/results/previous.json" \
    --current "${OUT_DIR}/results.json" \
    --output "${OUT_DIR}/diff.json" || true
fi

exit "${RUNNER_EXIT}"
