"""Plan config rendering."""

from __future__ import annotations

import json

from config_render import CONFIG_DIR, endpoint_mapping, load_json, render_plan_config, render_value


def test_render_value_substitutes_mapping():
    assert render_value("${A}/x", {"A": "http://a"}) == "http://a/x"


def test_render_value_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("SOME_ENDPOINT", "http://from-env")
    assert render_value("${SOME_ENDPOINT}", {}) == "http://from-env"


def test_unknown_placeholder_is_left_intact():
    assert render_value("${NOT_SET_ANYWHERE}", {}) == "${NOT_SET_ANYWHERE}"


def test_render_value_walks_lists_and_dicts():
    rendered = render_value({"a": ["${X}"], "b": {"c": "${X}"}}, {"X": "v"})
    assert rendered == {"a": ["v"], "b": {"c": "v"}}


def test_endpoint_mapping_normalises_trailing_slashes():
    mapping = endpoint_mapping("http://certify-nginx/", "http://verify:8080/v1/verify/", "Farmer")
    assert mapping["CERTIFY_ISSUER_URL"] == "http://certify-nginx"
    assert mapping["VERIFY_ENDPOINT"] == "http://verify:8080/v1/verify"
    assert mapping["CERTIFY_CREDENTIAL_CONFIGURATION_ID"] == "Farmer"
    # api-testrig's own endpoint name maps onto the issuer URL.
    assert mapping["ENV_ENDPOINT"] == "http://certify-nginx"


def test_issuer_plan_renders_the_key_the_suite_requires():
    """The suite declares @ConfigurationFields({"vci.credential_issuer_url"})."""
    mapping = endpoint_mapping("http://certify-nginx", "http://verify:8080/v1/verify", "Farmer")
    rendered = render_plan_config(CONFIG_DIR / "issuer-plan.json", mapping)
    assert rendered["vci"]["credential_issuer_url"] == "http://certify-nginx"
    assert rendered["vci"]["credential_configuration_id"] == "Farmer"
    assert rendered["alias"] == "inji-certify-openid-1_0"


def test_verifier_plan_renders_its_endpoint():
    mapping = endpoint_mapping("http://certify-nginx", "http://verify:8080/v1/verify", "Farmer")
    rendered = render_plan_config(CONFIG_DIR / "verifier-plan.json", mapping)
    assert rendered["server"]["discoveryUrl"] == "http://verify:8080/v1/verify"
    assert rendered["alias"] == "inji-verify-openid-1_0"


def test_committed_plan_names_are_the_ones_documented():
    plans = load_json(CONFIG_DIR / "plans.json")
    assert plans["certify"]["planName"] == "oid4vci-1_0-issuer-test-plan"
    assert plans["verify"]["planName"] == "oid4vp-1final-verifier-haip-test-plan"


def test_committed_configs_declare_an_alias():
    """An alias forces serial modules - the runner relies on being able to see it."""
    for name in ("issuer-plan.json", "verifier-plan.json"):
        assert load_json(CONFIG_DIR / name).get("alias")


def test_variant_files_are_valid_json_with_string_values():
    for name in ("issuer-variant.json", "verifier-variant.json"):
        variant = load_json(CONFIG_DIR / name)
        assert variant, f"{name} should not be empty"
        assert all(isinstance(value, str) for value in variant.values())


def test_rendered_document_is_json_serialisable():
    mapping = endpoint_mapping("http://c", "http://v", "F")
    rendered = render_plan_config(CONFIG_DIR / "issuer-plan.json", mapping)
    assert json.loads(json.dumps(rendered)) == rendered
