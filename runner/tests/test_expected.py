"""Expected failure / skip loading and matching."""

from __future__ import annotations

import json

from expected import (
    load_conditions,
    load_expected_failures,
    load_expected_skips,
    matches,
    normalize_condition_entry,
    select,
)


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_loads_the_oidf_condition_schema(tmp_path):
    path = _write(
        tmp_path,
        "expected-failures.json",
        {
            "conditions": [
                {
                    "test-name": "oid4vci-1_0-issuer-*",
                    "configuration-filename": "issuer-plan.json",
                    "variant": "*",
                    "current-block": "Credential endpoint",
                    "condition": "ValidateCredentialResponseSignature",
                    "expected-result": "failure",
                    "comment": "tracked in ISSUE-123",
                }
            ]
        },
    )
    modules, conditions = load_expected_failures(path)
    assert modules == {}
    assert len(conditions) == 1
    rule = conditions[0]
    assert rule["test-name"] == "oid4vci-1_0-issuer-*"
    assert rule["expected-result"] == "failure"
    assert rule["comment"] == "tracked in ISSUE-123"
    assert rule["__used"] is False


def test_top_level_list_is_accepted(tmp_path):
    path = _write(
        tmp_path,
        "expected-failures.json",
        [{"test-name": "m", "condition": "c", "expected-result": "warning"}],
    )
    _, conditions = load_expected_failures(path)
    assert conditions[0]["expected-result"] == "warning"


def test_harness_module_map_is_still_supported(tmp_path):
    path = _write(
        tmp_path,
        "expected-failures.json",
        {"modules": {"oid4vci-1_0-issuer-client-attestation": "not implemented in 1.0"}},
    )
    modules, conditions = load_expected_failures(path)
    assert modules == {"oid4vci-1_0-issuer-client-attestation": "not implemented in 1.0"}
    assert conditions == []


def test_module_list_with_reasons_is_supported(tmp_path):
    path = _write(
        tmp_path,
        "expected-failures.json",
        {"modules": ["plain-name", {"testModule": "named", "reason": "because"}]},
    )
    modules, _ = load_expected_failures(path)
    assert modules == {"plain-name": "expected", "named": "because"}


def test_missing_file_is_not_an_error(tmp_path):
    missing = tmp_path / "nope.json"
    assert load_expected_failures(missing) == ({}, [])
    assert load_expected_skips(missing) == (set(), [])
    assert load_conditions(missing) == []


def test_expected_skips_reads_module_names(tmp_path):
    path = _write(
        tmp_path,
        "expected-skips.json",
        {
            "modules": [
                "oid4vp-1final-verifier-happy-flow",
                {"testModule": "oid4vp-1final-verifier-alternate-happy-flow"},
            ]
        },
    )
    names, conditions = load_expected_skips(path)
    assert names == {
        "oid4vp-1final-verifier-happy-flow",
        "oid4vp-1final-verifier-alternate-happy-flow",
    }
    assert conditions == []


def test_wildcards_match_test_name_and_config():
    rule = normalize_condition_entry(
        {"test-name": "oid4vci-*", "configuration-filename": "issuer-*.json"}
    )
    assert matches(rule, "oid4vci-1_0-issuer-happy-flow", "issuer-plan.json", {})
    assert not matches(rule, "oid4vp-1final-verifier", "issuer-plan.json", {})
    assert not matches(rule, "oid4vci-1_0-issuer-happy-flow", "verifier-plan.json", {})


def test_partial_variant_matches_subset_only():
    rule = normalize_condition_entry(
        {"test-name": "*", "variant": {"credential_format": "sd_jwt_vc"}}
    )
    assert matches(rule, "m", "c.json", {"credential_format": "sd_jwt_vc", "extra": "x"})
    assert not matches(rule, "m", "c.json", {"credential_format": "mdoc"})
    assert not matches(rule, "m", "c.json", {})


def test_variant_star_matches_everything():
    rule = normalize_condition_entry({"test-name": "*", "variant": "*"})
    assert matches(rule, "m", "c.json", {"anything": "value"})
    assert matches(rule, "m", "c.json", None)


def test_select_returns_only_relevant_rules_and_resets_used():
    used = normalize_condition_entry({"test-name": "a"})
    unused = normalize_condition_entry({"test-name": "b"})
    used["__used"] = True
    chosen = select([used, unused], "a", "c.json", {})
    assert chosen == [used]
    assert used["__used"] is False


def test_aliases_are_accepted_for_field_names():
    rule = normalize_condition_entry(
        {"test_name": "m", "configuration_filename": "c.json", "expected_result": "WARNING"}
    )
    assert rule["test-name"] == "m"
    assert rule["configuration-filename"] == "c.json"
    assert rule["expected-result"] == "warning"


def test_defaults_are_permissive():
    rule = normalize_condition_entry({})
    assert rule["test-name"] == "*"
    assert rule["configuration-filename"] == "*"
    assert rule["current-block"] == "*"
    assert rule["condition"] == "*"
    assert rule["expected-result"] == "failure"
