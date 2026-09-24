"""The conformance benchmark gate.

This replaces the original ``passed / (passed + failed + skipped)`` rate, which
could never be satisfied: every expected failure or documented handoff skip
pushed the rate below ``minPassRate`` and failed the build, so the expected-
failures file and the gate cancelled each other out.

The model here is the api-testrig one: a stored benchmark of what a healthy
run looks like, compared against the current run, with the build failing on
regressions and on unexpected conditions.

Two rates are reported:

``passRate``
    ``passed / (passed + failed)`` - computed over modules that actually
    produced a verdict. Modules that were skipped by design (expected skips,
    expected failures, wallet handoffs) are excluded rather than counted as
    failures.

``conditionSuccessRate``
    ``SUCCESS / (SUCCESS + WARNING + FAILURE)`` over individual conditions.
    This is the finer grained signal and catches a module that still reports
    PASSED while emitting failing conditions.
"""

from __future__ import annotations

from typing import Any, Optional

DEFAULTS: dict[str, Any] = {
    # pass rate across adjudicated modules
    "minPassRate": 1.0,
    # any failure not covered by expected-failures.json fails the run
    "failOnUnexpectedFailure": True,
    # warnings are tolerated by default but counted and reported
    "failOnUnexpectedWarning": False,
    "maxUnexpectedWarnings": 0,
    "failOnUnexpectedSkip": False,
    "maxUnexpectedSkips": 0,
    # an expected-failure rule that no longer fires means the file is stale
    "failOnStaleExpectation": True,
    # wallet handoff skips are a known limitation, not a regression
    "failOnHandoff": False,
    # modules that must produce a verdict
    "requiredModules": [],
    # condition level floor
    "minConditionSuccessRate": 0.0,
    # fail when the diff against a previous run shows a regression
    "failOnRegression": False,
}


def _rate(numerator: int, denominator: int, empty: float = 1.0) -> float:
    if denominator <= 0:
        return empty
    return numerator / denominator


def metrics_for(summary: dict[str, Any]) -> dict[str, Any]:
    passed = int(summary.get("passed") or 0)
    graded_failures = int(summary.get("gradedFailures") or 0)
    if "gradedFailures" not in summary:
        # Fallback for older results.json documents.
        graded_failures = int(summary.get("failed") or 0) - int(
            summary.get("toleratedFailures") or 0
        )
    tolerated = int(summary.get("toleratedFailures") or 0)
    conditions = summary.get("conditions") or {}
    success = int(conditions.get("SUCCESS") or 0)
    warning = int(conditions.get("WARNING") or 0)
    failure = int(conditions.get("FAILURE") or 0)
    # Modules that were expected to fail are excluded from the denominator as
    # well as the numerator, so declaring a known gap never moves the rate.
    adjudicated = passed + graded_failures
    return {
        "passRate": _rate(passed, adjudicated),
        "adjudicatedModules": adjudicated,
        "toleratedFailures": tolerated,
        "gradedFailures": graded_failures,
        "conditionSuccessRate": _rate(success, success + warning + failure),
        "conditionCounts": {"SUCCESS": success, "WARNING": warning, "FAILURE": failure},
        "unexpectedFailures": int(summary.get("unexpectedFailures") or 0),
        "unexpectedWarnings": int(summary.get("unexpectedWarnings") or 0),
        "unexpectedSkips": int(summary.get("unexpectedSkips") or 0),
        "handoffSkips": int(summary.get("handoffSkips") or 0),
        "staleExpectations": int(summary.get("staleExpectations") or 0),
    }


def evaluate(
    summary: dict[str, Any],
    benchmark: Optional[dict[str, Any]] = None,
    diff: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Evaluate the benchmark. Returns ``{met, reasons, metrics, checks}``."""
    config = dict(DEFAULTS)
    config.update({k: v for k, v in (benchmark or {}).items() if k in DEFAULTS})
    metrics = metrics_for(summary)
    checks: list[dict[str, Any]] = []
    reasons: list[str] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            reasons.append(detail)

    min_rate = float(config["minPassRate"])
    check(
        "minPassRate",
        metrics["passRate"] + 1e-9 >= min_rate,
        f"pass rate {metrics['passRate']:.2%} over {metrics['adjudicatedModules']} "
        f"adjudicated module(s) < minPassRate {min_rate:.2%}",
    )

    if config["failOnUnexpectedFailure"]:
        count = metrics["unexpectedFailures"]
        check("unexpectedFailures", count == 0, f"{count} unexpected failure(s)")

    if config["failOnUnexpectedWarning"]:
        allowed = int(config["maxUnexpectedWarnings"])
        count = metrics["unexpectedWarnings"]
        check(
            "unexpectedWarnings",
            count <= allowed,
            f"{count} unexpected warning(s) exceeds allowed {allowed}",
        )

    if config["failOnUnexpectedSkip"]:
        allowed = int(config["maxUnexpectedSkips"])
        count = metrics["unexpectedSkips"]
        check(
            "unexpectedSkips",
            count <= allowed,
            f"{count} unexpected skip(s) exceeds allowed {allowed}",
        )

    if config["failOnStaleExpectation"]:
        count = metrics["staleExpectations"]
        check(
            "staleExpectations",
            count == 0,
            f"{count} expected failure(s) did not happen - expected-failures.json is stale",
        )

    if config["failOnHandoff"]:
        count = metrics["handoffSkips"]
        check("handoffSkips", count == 0, f"{count} module(s) blocked on wallet handoff")

    required = [str(item) for item in (config["requiredModules"] or [])]
    if required:
        ran = set(summary.get("ranModules") or [])
        adjudicated = set(summary.get("passedModules") or []) | set(
            summary.get("failedModules") or []
        )
        missing = sorted(set(required) - ran)
        unverified = sorted(set(required) & (ran - adjudicated))
        check(
            "requiredModules",
            not missing,
            f"missing required modules: {missing}",
        )
        check(
            "requiredModulesVerified",
            not unverified,
            f"required modules did not produce a verdict (skipped): {unverified}",
        )

    min_condition = float(config["minConditionSuccessRate"])
    if min_condition > 0:
        check(
            "minConditionSuccessRate",
            metrics["conditionSuccessRate"] + 1e-9 >= min_condition,
            f"condition success rate {metrics['conditionSuccessRate']:.2%} "
            f"< minConditionSuccessRate {min_condition:.2%}",
        )

    if config["failOnRegression"] and diff is not None:
        regressions = diff.get("regressions") or []
        check(
            "regressions",
            not regressions,
            f"{len(regressions)} regression(s) against the previous run: "
            f"{[item.get('module') for item in regressions][:5]}",
        )

    return {
        "met": not reasons,
        "reasons": reasons,
        "metrics": metrics,
        "checks": checks,
    }


def describe(result: dict[str, Any]) -> str:
    """One-line-per-check rendering for the console."""
    lines = []
    metrics = result.get("metrics") or {}
    lines.append(
        f"pass rate {metrics.get('passRate', 0):.2%} "
        f"({metrics.get('adjudicatedModules', 0)} adjudicated), "
        f"conditions {metrics.get('conditionCounts')}"
    )
    for check in result.get("checks") or []:
        lines.append(f"  [{'ok' if check['ok'] else 'FAIL'}] {check['name']}: {check['detail']}")
    return "\n".join(lines)
