"""Mapping conformance module outcomes onto PASS / FAIL / SKIP and summarising.

Kept deliberately explicit: every module resolves to exactly one mapped value
plus the evidence for it, so the report never has to guess why something was
green.
"""

from __future__ import annotations

from typing import Any, Optional

# api/info result values. WARNING and REVIEW count as a pass of the module
# (the spec was met) but they are still recorded as conditions.
PASS_RESULTS = frozenset({"PASSED", "PASSED_WITH_WARNINGS", "WARNING", "REVIEW"})
FAIL_RESULTS = frozenset({"FAILED", "FAILURE", "INTERRUPTED"})
SKIP_RESULTS = frozenset({"SKIPPED", "SKIP", "NOT_RUN"})

# Outcomes returned by OidfClient.wait_for_settled.
SETTLED_FINISHED = "FINISHED"
SETTLED_INTERRUPTED = "INTERRUPTED"
SETTLED_HANDOFF = "WAITING"
SETTLED_UNSTARTED = "CONFIGURED"
SETTLED_TIMEOUT = "TIMEOUT"
SETTLED_ERROR = "ERROR"
# The module was not driven at all because of --only / --skip selection.
SETTLED_FILTERED = "FILTERED"


def module_key(name: str, variant: Optional[dict]) -> str:
    """Stable key for a module+variant, matching the official driver's format.

    ``oidcc-server[client_auth_type=client_secret_basic][response_mode=default]``
    """
    if not variant:
        return name
    parts = "".join(f"[{key}={variant[key]}]" for key in sorted(variant))
    return name + parts


def map_result(raw_result: str, expected_failure: bool) -> tuple[str, Optional[str]]:
    """Map a suite result to PASS / FAIL / SKIP.

    Returns ``(mapped, reason)``. An empty result on a finished module is a
    FAIL rather than a silent pass - the official driver also treats an
    unknown result value as an unexpected failure.
    """
    status = (raw_result or "").upper()
    if not status:
        return "FAIL", "module finished without reporting a result"
    if expected_failure and status in FAIL_RESULTS:
        return "SKIP", "listed in expected-failures.json"
    if status in PASS_RESULTS:
        return "PASS", None
    if status in SKIP_RESULTS:
        return "SKIP", None
    if status in FAIL_RESULTS:
        return "FAIL", None
    return "FAIL", f"unrecognised result '{status}'"


def make_module(
    *,
    component: str,
    plan_name: str,
    config_file: str,
    test_module: str,
    variant: Optional[dict],
    test_id: Optional[str] = None,
    status: Optional[str] = None,
    result: Optional[str] = None,
    mapped: str = "SKIP",
    expected_failure: bool = False,
    expected_skip: bool = False,
    handoff: bool = False,
    filtered: bool = False,
    outcome: str = "",
    reason: Optional[str] = None,
    error: Optional[str] = None,
    analysis: Optional[dict] = None,
) -> dict[str, Any]:
    """Build one module record for results.json.

    Field names match what the Java ResultMapper already reads
    (testModule/testId/status/result/mapped/expectedFailure/expectedSkip/reason)
    plus additive fields the report can use.
    """
    record: dict[str, Any] = {
        "testModule": test_module,
        "key": module_key(test_module, variant),
        "component": component,
        "planName": plan_name,
        "configFile": config_file,
        "variant": variant,
        "testId": test_id,
        "status": status,
        "result": result,
        "mapped": mapped,
        "expectedFailure": expected_failure,
        "expectedSkip": expected_skip,
        "handoff": handoff,
        "filtered": filtered,
        "outcome": outcome,
        "reason": reason,
    }
    if error:
        record["error"] = error
    if analysis:
        record["counts"] = analysis.get("counts")
        record["logEntries"] = analysis.get("logEntries")
        record["unexpectedFailures"] = analysis.get("unexpectedFailures") or []
        record["unexpectedWarnings"] = analysis.get("unexpectedWarnings") or []
        record["expectedFailures"] = analysis.get("expectedFailures") or []
        record["expectedFailuresDidNotHappen"] = (
            analysis.get("expectedFailuresDidNotHappen") or []
        )
        record["unexpectedSkip"] = bool(analysis.get("unexpectedSkip"))
    return record


def summarize(plans: list[dict]) -> dict[str, Any]:
    """Aggregate every module across the plans of one run."""
    passed = failed = skipped = 0
    handoff = 0
    graded_failures = 0
    module_failures = 0
    condition_failures = 0
    unexpected_warnings = 0
    unexpected_skips = 0
    stale_expectations = 0
    tolerated_failures = 0
    errors = 0
    modules_total = 0
    conditions = {"SUCCESS": 0, "WARNING": 0, "FAILURE": 0}
    ran: list[str] = []
    adjudicated: list[str] = []
    passed_modules: list[str] = []
    failed_modules: list[str] = []
    skipped_modules: list[str] = []
    filtered_modules: list[str] = []

    for plan in plans:
        for module in plan.get("modules") or []:
            name = module.get("testModule") or ""
            modules_total += 1
            # A module removed by --only / --skip never ran, so it must not
            # count as a module that ran: requiredModules is checked against
            # this list, and a filtered run must not satisfy a required module.
            if module.get("filtered"):
                filtered_modules.append(name)
            else:
                ran.append(name)
            counts = module.get("counts") or {}
            for key in conditions:
                try:
                    conditions[key] += int(counts.get(key) or 0)
                except (TypeError, ValueError):
                    pass

            mapped = module.get("mapped")
            if mapped == "PASS":
                passed += 1
                adjudicated.append(name)
                passed_modules.append(name)
            elif mapped == "FAIL":
                failed += 1
                failed_modules.append(name)
                # A failure we declared acceptable up front is tolerated and is
                # not graded; anything else must pass.
                if module.get("expectedFailure"):
                    tolerated_failures += 1
                else:
                    graded_failures += 1
                    adjudicated.append(name)
                    module_failures += 1
            else:
                skipped += 1
                skipped_modules.append(name)
                if module.get("handoff"):
                    handoff += 1
                elif module.get("unexpectedSkip"):
                    unexpected_skips += 1
                elif module.get("expectedFailure"):
                    # An expected failure maps to SKIP rather than FAIL.
                    tolerated_failures += 1

            # Condition level failures count even when the module itself
            # reported PASSED - this is the signal the official driver acts on
            # and the one a module result alone would hide.
            condition_failures += len(module.get("unexpectedFailures") or [])
            unexpected_warnings += len(module.get("unexpectedWarnings") or [])
            stale_expectations += len(module.get("expectedFailuresDidNotHappen") or [])
            if module.get("error"):
                errors += 1

    return {
        "passed": passed,
        "failed": failed,
        "gradedFailures": graded_failures,
        "skipped": skipped,
        "handoffSkips": handoff,
        "total": modules_total,
        "ranModules": ran,
        "passedModules": passed_modules,
        "failedModules": failed_modules,
        "skippedModules": skipped_modules,
        "filteredModules": filtered_modules,
        "filtered": len(filtered_modules),
        "adjudicatedModules": len(adjudicated),
        "gradedModules": passed + graded_failures,
        "unexpectedFailures": module_failures + condition_failures,
        "moduleUnexpectedFailures": module_failures,
        "conditionUnexpectedFailures": condition_failures,
        "toleratedFailures": tolerated_failures,
        "unexpectedWarnings": unexpected_warnings,
        "unexpectedSkips": unexpected_skips,
        "staleExpectations": stale_expectations,
        "errors": errors,
        "conditions": conditions,
    }
