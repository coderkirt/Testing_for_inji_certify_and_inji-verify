"""Condition level adjudication of a module log."""

from __future__ import annotations

import expected as expected_module
from conditions import analyze_logs


def _rule(**kwargs):
    return expected_module.normalize_condition_entry(kwargs)


def test_happy_log_has_no_unexpected_conditions(load_fixture):
    analysis = analyze_logs(load_fixture("log-issuer-happy.json"), "PASSED", [], [])
    assert analysis["counts"] == {"SUCCESS": 5, "WARNING": 0, "FAILURE": 0}
    assert analysis["unexpectedFailures"] == []
    assert analysis["unexpectedWarnings"] == []
    assert analysis["expectedFailuresDidNotHappen"] == []


def test_failure_and_warning_are_surfaced_with_their_block(load_fixture):
    analysis = analyze_logs(load_fixture("log-issuer-with-failure.json"), "FAILED", [], [])
    assert analysis["counts"] == {"SUCCESS": 6, "WARNING": 1, "FAILURE": 1}
    assert analysis["unexpectedFailures"] == [
        {"current_block": "Credential endpoint", "src": "ValidateCredentialResponseSignature"}
    ]
    assert analysis["unexpectedWarnings"] == [
        {
            "current_block": "Authorization endpoint",
            "src": "EnsureIdTokenDoesNotContainNonRequestedClaims",
        }
    ]


def test_expected_failure_rule_suppresses_the_failure(load_fixture):
    rule = _rule(
        **{
            "test-name": "*",
            "configuration-filename": "*",
            "current-block": "Credential endpoint",
            "condition": "ValidateCredentialResponseSignature",
            "expected-result": "failure",
        }
    )
    analysis = analyze_logs(load_fixture("log-issuer-with-failure.json"), "FAILED", [rule], [])
    assert analysis["unexpectedFailures"] == []
    assert analysis["expectedFailures"] == [
        {"current_block": "Credential endpoint", "src": "ValidateCredentialResponseSignature"}
    ]
    # The warning is still unexpected because no rule covers it.
    assert len(analysis["unexpectedWarnings"]) == 1


def test_expected_warning_rule_suppresses_the_warning(load_fixture):
    rule = _rule(
        **{
            "current-block": "Authorization endpoint",
            "condition": "EnsureIdTokenDoesNotContainNonRequestedClaims",
            "expected-result": "warning",
        }
    )
    analysis = analyze_logs(load_fixture("log-issuer-with-failure.json"), "FAILED", [rule], [])
    assert analysis["unexpectedWarnings"] == []
    assert analysis["expectedWarnings"] == [
        {
            "current_block": "Authorization endpoint",
            "src": "EnsureIdTokenDoesNotContainNonRequestedClaims",
        }
    ]


def test_rule_that_never_fires_is_reported_as_stale(load_fixture):
    rule = _rule(
        **{
            "current-block": "Credential endpoint",
            "condition": "ThisConditionDoesNotExist",
            "expected-result": "failure",
        }
    )
    analysis = analyze_logs(load_fixture("log-issuer-happy.json"), "PASSED", [rule], [])
    assert analysis["expectedFailuresDidNotHappen"] == [
        "Credential endpoint / ThisConditionDoesNotExist"
    ]


def test_wildcard_block_matches_any_block(load_fixture):
    rule = _rule(
        **{"current-block": "*", "condition": "ValidateCredentialResponseSignature"}
    )
    analysis = analyze_logs(load_fixture("log-issuer-with-failure.json"), "FAILED", [rule], [])
    assert analysis["unexpectedFailures"] == []


def test_entries_without_a_result_are_ignored(load_fixture):
    logs = [{"src": "Informational"}]
    analysis = analyze_logs(logs, "PASSED", [], [])
    assert analysis["counts"] == {"SUCCESS": 0, "WARNING": 0, "FAILURE": 0}
    assert analysis["logEntries"] == 1


def test_success_entries_never_count_as_unexpected():
    logs = [{"result": "SUCCESS", "src": "Whatever"}]
    analysis = analyze_logs(logs, "PASSED", [], [])
    assert analysis["unexpectedFailures"] == []
    assert analysis["unexpectedWarnings"] == []


def test_skip_without_a_rule_is_an_unexpected_skip():
    analysis = analyze_logs([], "SKIPPED", [], [])
    assert analysis["unexpectedSkip"] is True
    assert analysis["expectedSkip"] is False


def test_skip_with_a_rule_is_expected():
    rule = _rule(**{"test-name": "*", "comment": "needs a wallet"})
    analysis = analyze_logs([], "SKIPPED", [], [rule])
    assert analysis["unexpectedSkip"] is False
    assert analysis["expectedSkip"] is True
    assert analysis["skipComment"] == "needs a wallet"


def test_expected_skip_that_did_not_happen_is_reported():
    rule = _rule(**{"test-name": "*"})
    analysis = analyze_logs([], "PASSED", [], [rule])
    assert analysis["expectedSkipDidNotHappen"] is True
    assert analysis["unexpectedSkip"] is False


def test_failed_also_satisfies_an_expected_skip():
    """Matches the official driver: SKIPPED or FAILED satisfy an expected skip."""
    rule = _rule(**{"test-name": "*"})
    analysis = analyze_logs([], "FAILED", [], [rule])
    assert analysis["expectedSkip"] is True
