"""The benchmark gate.

The first test is the regression test for the original bug: the gate used to
compute ``passed / (passed + failed + skipped)``, so every documented skip made
``minPassRate: 1.0`` unreachable and the build failed on a healthy run.
"""

from __future__ import annotations

from benchmark import describe, evaluate, metrics_for
from results import make_module, summarize


def _summary(*modules):
    return summarize([{"modules": list(modules)}])


def _module(name, mapped, **kwargs):
    return make_module(
        component="certify",
        plan_name="plan",
        config_file="issuer-plan.json",
        test_module=name,
        variant=None,
        mapped=mapped,
        **kwargs,
    )


def _healthy_run(load_fixture):
    """A passing run containing an expected failure and a handoff skip."""
    return summarize(load_fixture("results-with-expected-failures.json")["plans"])


def test_expected_failures_and_handoff_skips_do_not_fail_the_gate(load_fixture):
    summary = _healthy_run(load_fixture)
    result = evaluate(summary, {"minPassRate": 1.0})
    assert result["met"] is True, result["reasons"]
    # The pass rate is computed over modules that produced a verdict, so the
    # two documented skips are excluded rather than counted as failures.
    assert result["metrics"]["passRate"] == 1.0
    assert result["metrics"]["adjudicatedModules"] == 2


def test_old_formula_would_have_rejected_that_run(load_fixture):
    summary = _healthy_run(load_fixture)
    naive_rate = summary["passed"] / summary["total"]
    assert naive_rate < 1.0  # what the original gate measured
    assert evaluate(summary, {"minPassRate": 1.0})["met"] is True


def test_unexpected_failure_fails_the_gate():
    result = evaluate(_summary(_module("m", "FAIL")), {})
    assert result["met"] is False
    assert "unexpected failure" in " ".join(result["reasons"])


def test_expected_failure_does_not_fail_the_gate():
    result = evaluate(_summary(_module("m", "FAIL", expected_failure=True)), {})
    assert result["met"] is True, result["reasons"]
    assert result["metrics"]["unexpectedFailures"] == 0


def test_expected_failure_mapped_to_skip_does_not_fail_the_gate():
    """The real shape: map_result turns an expected failure into a SKIP."""
    summary = _summary(
        _module("m", "SKIP", expected_failure=True, result="FAILED"),
        _module("n", "PASS"),
    )
    result = evaluate(summary, {"minPassRate": 1.0})
    assert result["met"] is True, result["reasons"]


def test_stale_expected_failure_is_reported():
    module = _module("m", "PASS")
    module["expectedFailuresDidNotHappen"] = [
        {"current_block": "Credential endpoint", "src": "SomeCondition"}
    ]
    result = evaluate(_summary(module), {})
    assert result["met"] is False
    assert "did not happen" in " ".join(result["reasons"])


def test_stale_expectations_can_be_tolerated():
    module = _module("m", "PASS")
    module["expectedFailuresDidNotHappen"] = [{"src": "SomeCondition"}]
    result = evaluate(_summary(module), {"failOnStaleExpectation": False})
    assert result["met"] is True


def test_unexpected_warnings_are_visible_but_tolerated_by_default():
    module = _module("m", "PASS")
    module["unexpectedWarnings"] = [{"src": "SomeWarning"}]
    result = evaluate(_summary(module), {})
    assert result["met"] is True
    assert result["metrics"]["unexpectedWarnings"] == 1

    strict = evaluate(_summary(module), {"failOnUnexpectedWarning": True})
    assert strict["met"] is False


def test_gate_uses_results_json_fixture_metrics(load_fixture):
    metrics = metrics_for(_healthy_run(load_fixture))
    assert metrics["conditionSuccessRate"] == 49 / 52
    assert metrics["conditionCounts"] == {"SUCCESS": 49, "WARNING": 1, "FAILURE": 2}


def test_required_module_must_produce_a_verdict():
    summary = _summary(
        _module("must-run", "SKIP", expected_skip=True),
        _module("other", "PASS"),
    )
    result = evaluate(summary, {"requiredModules": ["must-run"]})
    assert result["met"] is False
    assert "did not produce a verdict" in " ".join(result["reasons"])


def test_required_module_that_passed_is_satisfied():
    result = evaluate(_summary(_module("must-run", "PASS")), {"requiredModules": ["must-run"]})
    assert result["met"] is True, result["reasons"]


def test_missing_required_module_is_reported():
    result = evaluate(_summary(_module("other", "PASS")), {"requiredModules": ["absent"]})
    assert result["met"] is False
    assert "missing required modules" in " ".join(result["reasons"])


def test_regression_against_previous_run_fails_when_enabled():
    """The current run is green, but it regressed against the benchmark baseline."""
    diff = {"regressions": [{"module": "certify::m", "from": "PASS", "to": "FAIL"}]}
    summary = _summary(_module("m", "PASS"))
    assert evaluate(summary, {"failOnRegression": False}, diff)["met"] is True
    strict = evaluate(summary, {"failOnRegression": True}, diff)
    assert strict["met"] is False
    assert "regression" in " ".join(strict["reasons"])


def test_tolerated_failure_is_excluded_from_the_pass_rate():
    """Declaring a known gap must not move the pass rate in either direction."""
    summary = _summary(
        _module("known-gap", "FAIL", expected_failure=True),
        _module("good", "PASS"),
    )
    result = evaluate(summary, {"minPassRate": 1.0})
    assert result["met"] is True, result["reasons"]
    assert result["metrics"]["passRate"] == 1.0
    assert result["metrics"]["toleratedFailures"] == 1
    assert result["metrics"]["adjudicatedModules"] == 1


def test_min_condition_success_rate_is_enforced():
    module = _module("m", "PASS")
    module["counts"] = {"SUCCESS": 5, "WARNING": 5, "FAILURE": 0}
    summary = _summary(module)
    assert evaluate(summary, {"minConditionSuccessRate": 0.6})["met"] is False
    assert evaluate(summary, {"minConditionSuccessRate": 0.5})["met"] is True


def test_handoff_can_be_made_fatal_if_desired(load_fixture):
    summary = _healthy_run(load_fixture)
    result = evaluate(summary, {"failOnHandoff": True})
    assert result["met"] is False
    assert "handoff" in " ".join(result["reasons"])


def test_describe_renders_every_check(load_fixture):
    rendered = describe(evaluate(_healthy_run(load_fixture), {}))
    assert "pass rate" in rendered
    assert "[ok]" in rendered
