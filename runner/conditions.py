"""Per-condition adjudication of an OpenID conformance suite module log.

The suite reports one *result* per module (PASSED / FAILED / WARNING / ...) but
the real signal lives in the condition log: each log entry carries its own
SUCCESS / WARNING / FAILURE result, and the official driver decides whether a
run is acceptable from those entries rather than from the module result alone.

This is a faithful port of ``analyze_result_logs`` in
``scripts/run-test-plan.py`` so the harness reaches the same verdicts as the
official driver:

* ``FAILURE`` entries not covered by an expected-failure rule are *unexpected
  failures* and fail the gate.
* ``WARNING`` entries not covered by an expected-warning rule are *unexpected
  warnings*.
* An expected-failure rule that never fires is itself a failure
  (``expected_failures_did_not_happen``) - this is what stops a stale
  expected-failures file from silently rotting.
* A module that reports ``SKIPPED`` without an expected-skip rule is an
  *unexpected skip*.
"""

from __future__ import annotations

import fnmatch
from typing import Any

CONDITION_RESULTS = ("SUCCESS", "WARNING", "FAILURE")
BLOCK_START_SRC = "-START-BLOCK-"

# Cap the per-module detail lists so results.json stays readable.
MAX_DETAIL = 25


def _block_timeline(logs: list[dict]) -> tuple[dict[str, str], list[dict]]:
    """Collect block ids -> block names, and the result-bearing entries."""
    block_names: dict[str, str] = {}
    results: list[dict] = []
    for entry in logs:
        if entry.get("startBlock") is True and entry.get("src") == BLOCK_START_SRC:
            block_names[str(entry.get("blockId"))] = str(entry.get("msg") or "")
            continue
        if "result" not in entry:
            continue
        results.append(entry)
    return block_names, results


def _detail(block: str, src: str) -> dict[str, str]:
    return {"current_block": block, "src": src}


def analyze_logs(
    logs: list[dict],
    module_result: str,
    expected_failures: list[dict],
    expected_skips: list[dict],
) -> dict[str, Any]:
    """Adjudicate one module's log.

    ``expected_failures`` / ``expected_skips`` must already be filtered to the
    entries that match this module (see ``expected.select``).
    """
    counts = {name: 0 for name in CONDITION_RESULTS}
    block_names, entries = _block_timeline(logs)

    unexpected_failures: list[dict] = []
    unexpected_warnings: list[dict] = []
    expected_failure_hits: list[dict] = []
    expected_warning_hits: list[dict] = []
    missing_src: list[str] = []

    for entry in entries:
        log_result = str(entry.get("result") or "").upper()
        if log_result not in counts:
            continue
        counts[log_result] += 1

        block_id = entry.get("blockId")
        block_msg = block_names.get(str(block_id), "") if block_id is not None else ""
        src = str(entry.get("src") or "")

        matched = False
        for rule in expected_failures:
            expected_block = rule.get("current-block") or "*"
            expected_condition = rule.get("condition") or "*"
            if expected_block not in ("*", block_msg):
                continue
            if not fnmatch.fnmatch(src, expected_condition):
                continue
            if (log_result == "FAILURE" and rule["expected-result"] == "failure") or (
                log_result == "WARNING" and rule["expected-result"] == "warning"
            ):
                if log_result == "FAILURE":
                    expected_failure_hits.append(_detail(block_msg, src))
                else:
                    expected_warning_hits.append(_detail(block_msg, src))
                rule["__used"] = True
                matched = True
                break

        if matched:
            continue
        if log_result == "FAILURE":
            unexpected_failures.append(_detail(block_msg, src))
        elif log_result == "WARNING":
            unexpected_warnings.append(_detail(block_msg, src))

    for rule in expected_failures:
        if rule.get("__used"):
            continue
        missing_src.append(
            f"{rule.get('current-block') or '*'} / {rule.get('condition') or '*'}"
        )

    # Skip handling mirrors the official driver: an expected-skip entry is
    # satisfied by SKIPPED or FAILED, anything else means the skip is stale.
    expected_skip = False
    expected_skip_did_not_happen = False
    skip_rule = None
    for rule in expected_skips:
        if module_result in ("SKIPPED", "FAILED"):
            expected_skip = True
            rule["__used"] = True
            skip_rule = rule
        else:
            expected_skip_did_not_happen = True

    unexpected_skip = module_result == "SKIPPED" and not expected_skip

    return {
        "counts": counts,
        "unexpectedFailures": unexpected_failures,
        "unexpectedWarnings": unexpected_warnings,
        "expectedFailures": expected_failure_hits,
        "expectedWarnings": expected_warning_hits,
        "expectedFailuresDidNotHappen": missing_src,
        "expectedSkip": expected_skip,
        "expectedSkipDidNotHappen": expected_skip_did_not_happen,
        "unexpectedSkip": unexpected_skip,
        "skipComment": (skip_rule or {}).get("comment") or "",
        "logEntries": len(logs),
    }


def trim(detail: list[dict]) -> list[dict]:
    return detail[:MAX_DETAIL]
