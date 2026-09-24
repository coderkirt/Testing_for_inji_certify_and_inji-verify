"""Module result mapping and summary aggregation."""

from __future__ import annotations

import pytest

from results import make_module, map_result, module_key, summarize


@pytest.mark.parametrize(
    "raw,expected_failure,mapped",
    [
        ("PASSED", False, "PASS"),
        ("PASSED_WITH_WARNINGS", False, "PASS"),
        # A module that satisfied the spec but emitted warnings still passes the
        # module; the warnings are surfaced separately as conditions.
        ("WARNING", False, "PASS"),
        ("REVIEW", False, "PASS"),
        ("SKIPPED", False, "SKIP"),
        ("FAILED", False, "FAIL"),
        ("INTERRUPTED", False, "FAIL"),
        ("FAILED", True, "SKIP"),
        ("PASSED", True, "PASS"),
        ("", False, "FAIL"),
        ("SOMETHING_NEW", False, "FAIL"),
    ],
)
def test_map_result(raw, expected_failure, mapped):
    assert map_result(raw, expected_failure)[0] == mapped


def test_empty_result_is_not_a_silent_pass():
    mapped, reason = map_result("", False)
    assert mapped == "FAIL"
    assert "without reporting a result" in reason


def test_expected_failure_reason_is_recorded():
    mapped, reason = map_result("FAILED", True)
    assert mapped == "SKIP"
    assert "expected-failures" in reason


def test_module_key_matches_official_format():
    assert module_key("plain", None) == "plain"
    assert module_key("plain", {}) == "plain"
    assert (
        module_key(
            "oidcc-server",
            {"response_mode": "default", "client_auth_type": "client_secret_basic"},
        )
        == "oidcc-server[client_auth_type=client_secret_basic][response_mode=default]"
    )


def test_summary_separates_handoff_from_unexpected_skips(load_fixture):
    document = load_fixture("results-with-expected-failures.json")
    summary = summarize(document["plans"])

    assert summary["passed"] == 2
    assert summary["failed"] == 0
    assert summary["skipped"] == 2
    assert summary["total"] == 4
    # One skip is a wallet handoff, one is a documented product gap. Neither is
    # an unexpected skip.
    assert summary["handoffSkips"] == 1
    assert summary["unexpectedSkips"] == 0
    assert summary["unexpectedFailures"] == 0
    assert summary["adjudicatedModules"] == 2
    assert summary["conditions"] == {"SUCCESS": 49, "WARNING": 1, "FAILURE": 2}


def test_summary_flags_a_genuinely_unexpected_skip():
    plan = {
        "modules": [
            make_module(
                component="verify",
                plan_name="p",
                config_file="c.json",
                test_module="m",
                variant=None,
                mapped="SKIP",
                outcome="FINISHED",
                analysis={"counts": {}, "unexpectedSkip": True},
            )
        ]
    }
    summary = summarize([plan])
    assert summary["unexpectedSkips"] == 1
    assert summary["handoffSkips"] == 0


def test_summary_counts_unexpected_failure_only_when_not_expected():
    plan = {
        "modules": [
            make_module(
                component="certify",
                plan_name="p",
                config_file="c.json",
                test_module="a",
                variant=None,
                mapped="FAIL",
                expected_failure=True,
            ),
            make_module(
                component="certify",
                plan_name="p",
                config_file="c.json",
                test_module="b",
                variant=None,
                mapped="FAIL",
            ),
        ]
    }
    summary = summarize([plan])
    assert summary["failed"] == 2
    assert summary["unexpectedFailures"] == 1
    assert summary["failedModules"] == ["a", "b"]


def test_module_record_keeps_fields_the_java_bridge_reads():
    record = make_module(
        component="certify",
        plan_name="plan",
        config_file="issuer-plan.json",
        test_module="oid4vci-1_0-issuer-happy-flow",
        variant={"credential_format": "sd_jwt_vc"},
        test_id="abc",
        status="FINISHED",
        result="PASSED",
        mapped="PASS",
    )
    for field in (
        "testModule",
        "testId",
        "status",
        "result",
        "mapped",
        "expectedFailure",
        "expectedSkip",
        "reason",
    ):
        assert field in record
