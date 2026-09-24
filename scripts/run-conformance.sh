#!/usr/bin/env bash
# One-command conformance harness.
#   ./scripts/run-conformance.sh --component certify
#   ./scripts/run-conformance.sh --component verify
#   ./scripts/run-conformance.sh --combined
#
# Flow: compose up (and wait for health) -> drive the suite REST API -> map the
# result into the TestNG/Extent bridge -> gate on the benchmark -> publish
# reports. Each stage can be skipped, and the runner's own flags can be passed
# straight through.
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
BASELINE=""
SAVE_BASELINE=0
VALIDATE_PLANS=0
PUBLISH_REPORTS=0
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-600}"
EXTRA_RUNNER_ARGS=()
RUNNER_FLAGS=()

usage() {
  cat <<'EOF'
Usage:
  run-conformance.sh --component certify|verify [options]
  run-conformance.sh --combined [options]

Options:
  --skip-compose         use an already running stack (CI starts it separately)
  --skip-testrig         run the Python runner only, skip the Maven bridge
  --parallel             run plans/modules concurrently where the suite allows it
  --official-script PATH drive the official run-test-plan.py instead of the REST client
  --validate-plans       check plan names and variant keys against the live suite, then exit
  --diff-against FILE    diff this run against a stored results.json
  --baseline FILE        benchmark baseline (defaults to results/baseline.json if present)
  --save-baseline        copy this run's results.json to results/baseline.json afterwards
  --publish-reports      push results/reports to the configured S3/MinIO bucket
  --expected-failures F  override runner/configs/expected-failures.json
  --expected-skips F     override runner/configs/expected-skips.json
  --benchmark F          override runner/configs/benchmark.json
  --module-timeout SECS  per-module timeout (default 600)
  --only PATTERN         run only modules matching a wildcard (repeatable, comma separated)
  --skip PATTERN         never run modules matching a wildcard (repeatable, comma separated)
  -h | --help            this help

Environment:
  CONFORMANCE_SERVER     default https://localhost.emobix.co.uk:8443/
  CERTIFY_ISSUER_URL     issuer URL the suite will call (docker DNS or host)
  VERIFY_ENDPOINT        verifier API the suite will call
  ENV_ENDPOINT           api-testrig endpoint; used as CERTIFY_ISSUER_URL when set
  HEALTH_TIMEOUT         seconds to wait for the stack (default 600)
  PUSH_REPORTS_TO_S3     on/off for --publish-reports (see runner/README.md)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --component) COMPONENT="${2:-}"; shift 2 ;;
    --combined) COMBINED=1; shift ;;
    --skip-compose) SKIP_COMPOSE=1; shift ;;
    --skip-testrig) SKIP_TESTRIG=1; shift ;;
    --parallel) PARALLEL=1; shift ;;
    --official-script) OFFICIAL_SCRIPT="${2:-}"; shift 2 ;;
    --diff-against) DIFF_AGAINST="${2:-}"; shift 2 ;;
    --baseline) BASELINE="${2:-}"; shift 2 ;;
    --save-baseline) SAVE_BASELINE=1; shift ;;
    --validate-plans) VALIDATE_PLANS=1; shift ;;
    --publish-reports) PUBLISH_REPORTS=1; shift ;;
    --expected-failures) RUNNER_FLAGS+=(--expected-failures "${2:-}"); shift 2 ;;
    --expected-skips) RUNNER_FLAGS+=(--expected-skips "${2:-}"); shift 2 ;;
    --benchmark) RUNNER_FLAGS+=(--benchmark "${2:-}"); shift 2 ;;
    --module-timeout) RUNNER_FLAGS+=(--module-timeout "${2:-}"); shift 2 ;;
    --only) RUNNER_FLAGS+=(--only "${2:-}"); shift 2 ;;
    --skip) RUNNER_FLAGS+=(--skip "${2:-}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) EXTRA_RUNNER_ARGS+=("$1"); shift ;;
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

# Read a key out of compose/.env without sourcing it.
env_value() {
  local key="$1" fallback="$2"
  local value=""
  if [[ -f "${ENV_FILE}" ]]; then
    value="$(grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  fi
  if [[ -z "${value}" ]]; then
    value="${fallback}"
  fi
  printf '%s' "${value}"
}

WAIT_CERTIFY=0
WAIT_VERIFY=0
if [[ "${MODE}" == "combined" || "${MODE}" == "certify" ]]; then WAIT_CERTIFY=1; fi
if [[ "${MODE}" == "combined" || "${MODE}" == "verify" ]]; then WAIT_VERIFY=1; fi

start_stack() {
  local services=(mongodb server nginx)
  if [[ "${WAIT_CERTIFY}" -eq 1 ]]; then services+=(certify-db certify certify-nginx); fi
  if [[ "${WAIT_VERIFY}" -eq 1 ]]; then services+=(verify-db verify-service verify-ui); fi
  echo "Starting services: ${services[*]}"
  # --wait blocks until every service with a healthcheck reports healthy, so a
  # crash-looping container fails here instead of surfacing later as a batch of
  # confusing conformance failures.
  compose up -d --wait --wait-timeout "${HEALTH_TIMEOUT}" "${services[@]}"
}

wait_http() {
  local url="$1"
  local name="$2"
  local attempts="${3:-48}"
  echo "Waiting for ${name} at ${url}"
  for ((i = 1; i <= attempts; i++)); do
    if curl -kfsS "${url}" >/dev/null 2>&1; then
      echo "${name} is up"
      return 0
    fi
    sleep 5
  done
  echo "Timed out waiting for ${name} (${url})" >&2
  return 1
}

if [[ "${SKIP_COMPOSE}" -eq 0 ]]; then
  start_stack
fi

export CONFORMANCE_SERVER="${CONFORMANCE_SERVER:-https://localhost.emobix.co.uk:8443/}"
if [[ -n "${ENV_ENDPOINT:-}" && -z "${CERTIFY_ISSUER_URL:-}" ]]; then
  export CERTIFY_ISSUER_URL="${ENV_ENDPOINT}"
fi
export CERTIFY_ISSUER_URL="${CERTIFY_ISSUER_URL:-http://certify-nginx}"
export VERIFY_ENDPOINT="${VERIFY_ENDPOINT:-http://verify-service:8080/v1/verify}"

# Wait on the host-facing endpoints. The suite is driven from the host, so it
# only needs to answer over HTTP; Certify and Verify must finish starting
# before the first plan is created or the first modules fail for no good reason.
if [[ "${SKIP_COMPOSE}" -eq 0 || "${FORCE_HEALTH_WAIT:-0}" == "1" ]]; then
  wait_http "${CONFORMANCE_SERVER}" "OpenID conformance suite" 48 || true
  if [[ "${WAIT_CERTIFY}" -eq 1 ]]; then
    CERTIFY_NGINX_PORT="$(env_value CERTIFY_NGINX_PORT 8091)"
    wait_http "http://127.0.0.1:${CERTIFY_NGINX_PORT}/.well-known/openid-credential-issuer" \
      "Inji Certify (issuer metadata)" 60
  fi
  if [[ "${WAIT_VERIFY}" -eq 1 ]]; then
    VERIFY_HOST_PORT="$(env_value VERIFY_HOST_PORT 8080)"
    wait_http "http://127.0.0.1:${VERIFY_HOST_PORT}/v1/verify/actuator/health" \
      "Inji Verify (service health)" 60
  fi
fi

OUT_DIR="${ROOT}/results/${MODE}"
BASELINE_DIR="${ROOT}/results"
mkdir -p "${OUT_DIR}" "${BASELINE_DIR}"

PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

# Reuse a stored baseline automatically so the regression gate is live by
# default once someone has saved one.
if [[ -z "${BASELINE}" && -f "${BASELINE_DIR}/baseline.json" ]]; then
  BASELINE="${BASELINE_DIR}/baseline.json"
fi

RUNNER_CMD=(
  "${PYTHON_BIN}" "${ROOT}/runner/run_conformance.py"
  --output-dir "${OUT_DIR}"
  --suite-url "${CONFORMANCE_SERVER}"
)
if [[ "${COMBINED}" -eq 1 ]]; then
  RUNNER_CMD+=(--combined)
else
  RUNNER_CMD+=(--component "${COMPONENT}")
fi
if [[ "${PARALLEL}" -eq 1 ]]; then RUNNER_CMD+=(--parallel); fi
if [[ "${VALIDATE_PLANS}" -eq 1 ]]; then RUNNER_CMD+=(--validate-plans); fi
if [[ -n "${OFFICIAL_SCRIPT}" ]]; then RUNNER_CMD+=(--official-script "${OFFICIAL_SCRIPT}"); fi
if [[ -n "${DIFF_AGAINST}" ]]; then RUNNER_CMD+=(--diff-against "${DIFF_AGAINST}"); fi
if [[ -n "${BASELINE}" ]]; then RUNNER_CMD+=(--baseline "${BASELINE}"); fi
if [[ ${#RUNNER_FLAGS[@]} -gt 0 ]]; then RUNNER_CMD+=("${RUNNER_FLAGS[@]}"); fi
if [[ ${#EXTRA_RUNNER_ARGS[@]} -gt 0 ]]; then RUNNER_CMD+=("${EXTRA_RUNNER_ARGS[@]}"); fi

echo "Running ${MODE} conformance"
set +e
"${RUNNER_CMD[@]}"
RUNNER_EXIT=$?
set -e

if [[ "${VALIDATE_PLANS}" -eq 1 ]]; then
  exit "${RUNNER_EXIT}"
fi

if [[ "${RUNNER_EXIT}" -ne 0 ]]; then
  echo "Conformance runner failed with exit code ${RUNNER_EXIT}" >&2
  echo "Results (if written): ${OUT_DIR}/results.json" >&2
fi

if [[ "${SKIP_TESTRIG}" -eq 0 && -f "${OUT_DIR}/results.json" ]]; then
  SUITE_XML="src/test/resources/testng-${MODE}.xml"
  echo "Mapping results into TestNG suite ${SUITE_XML}"
  mvn -f "${ROOT}/testrig-bridge/pom.xml" -Pconformance-suite test \
    -DsuiteXmlFile="${SUITE_XML}" \
    -Dconformance.results="${OUT_DIR}/results.json" \
    -Dconformance.component="${MODE}" \
    -Dconformance.reuseResults=true \
    -Dconformance.repoRoot="${ROOT}"
fi

if [[ "${PUBLISH_REPORTS}" -eq 1 || "${PUSH_REPORTS_TO_S3:-}" == "true" ]]; then
  echo "Publishing reports"
  S3_SOURCES=(--source "${ROOT}/results")
  if [[ -d "${ROOT}/testrig-bridge/target/extent" ]]; then
    S3_SOURCES+=(--source "${ROOT}/testrig-bridge/target/extent")
  fi
  "${PYTHON_BIN}" "${ROOT}/runner/s3_upload.py" \
    "${S3_SOURCES[@]}" \
    --run-id "$(basename "${OUT_DIR}")" || true
fi

if [[ "${SAVE_BASELINE}" -eq 1 && "${RUNNER_EXIT}" -eq 0 && -f "${OUT_DIR}/results.json" ]]; then
  cp "${OUT_DIR}/results.json" "${BASELINE_DIR}/baseline.json"
  echo "Saved benchmark baseline to ${BASELINE_DIR}/baseline.json"
fi

exit "${RUNNER_EXIT}"
