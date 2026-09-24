"""SigV4 signing and report publishing.

The signing test uses the canonical size-v4 test vector ("get-vanilla") that
the AWS SDKs themselves are tested against, so a regression in the signer is
caught rather than silently producing 403s against MinIO/S3.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from s3_upload import (
    DEFAULT_BUCKET,
    S3Config,
    _as_bool,
    load_config,
    object_url,
    sign_request,
    upload_reports,
)

TEST_ACCESS_KEY = "AKIDEXAMPLE"
TEST_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# aws-sig-v4-test-suite/get-vanilla/get-vanilla.authz
EXPECTED_GET_VANILLA = (
    "AWS4-HMAC-SHA256 "
    "Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
    "SignedHeaders=host;x-amz-date, "
    "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
)


def test_empty_payload_hash_constant():
    assert hashlib.sha256(b"").hexdigest() == EMPTY_SHA256


def test_sigv4_matches_the_official_test_vector():
    headers = sign_request(
        method="GET",
        url="https://example.amazonaws.com/",
        region="us-east-1",
        access_key=TEST_ACCESS_KEY,
        secret_key=TEST_SECRET_KEY,
        payload=b"",
        service="service",
        now=datetime(2015, 8, 30, 12, 36, 0, tzinfo=timezone.utc),
        sign_payload_header=False,
    )
    assert headers["Authorization"] == EXPECTED_GET_VANILLA


def test_signed_request_headers_include_amz_date_and_payload_hash():
    headers = sign_request(
        method="PUT",
        url="https://s3.us-east-1.amazonaws.com/automationtests/key.json",
        region="us-east-1",
        access_key=TEST_ACCESS_KEY,
        secret_key=TEST_SECRET_KEY,
        payload=b"{}",
        headers={"content-type": "application/json"},
    )
    assert headers["x-amz-date"].endswith("Z")
    assert headers["x-amz-content-sha256"] == hashlib.sha256(b"{}").hexdigest()
    assert "SignedHeaders=" in headers["Authorization"]
    assert "x-amz-content-sha256" in headers["Authorization"].split("SignedHeaders=")[1].split(",")[0]
    assert headers["content-type"] == "application/json"


def test_signature_changes_with_the_body():
    def sign(body: bytes) -> str:
        return sign_request(
            method="PUT",
            url="https://example.amazonaws.com/bucket/key",
            region="us-east-1",
            access_key=TEST_ACCESS_KEY,
            secret_key=TEST_SECRET_KEY,
            payload=body,
        )["Authorization"]

    assert sign(b"one") != sign(b"two")


def test_path_style_url_for_a_custom_endpoint():
    config = S3Config(endpoint="http://localhost:9000", bucket=DEFAULT_BUCKET, path_style=True)
    assert object_url(config, "reports/run.json") == (
        "http://localhost:9000/automationtests/reports/run.json"
    )


def test_virtual_hosted_style_url_for_aws():
    config = S3Config(region="eu-west-1", bucket="automationtests", path_style=False)
    assert object_url(config, "reports/run.json") == (
        "https://automationtests.s3.eu-west-1.amazonaws.com/reports/run.json"
    )


def test_object_keys_with_spaces_are_encoded():
    config = S3Config(endpoint="http://minio:9000", bucket="b", path_style=True)
    assert object_url(config, "a dir/a file.json").endswith("/b/a%20dir/a%20file.json")


def test_load_config_prefers_cli_over_environment(monkeypatch):
    monkeypatch.setenv("S3_ACCOUNT", "from-env")
    monkeypatch.setenv("S3_USER_KEY", "env-key")
    monkeypatch.setenv("PUSH_REPORTS_TO_S3", "true")
    config = load_config(cli={"s3_account": "from-cli", "s3_user_key": "cli-key"})
    assert config.bucket == "from-cli"
    assert config.access_key == "cli-key"
    assert config.enabled is True


def test_load_config_reads_the_apitest_commons_key_names(monkeypatch):
    monkeypatch.setenv("push-reports-to-s3", "yes")
    monkeypatch.setenv("s3-account", "automationtests")
    monkeypatch.setenv("s3-host", "http://minio.mosip.net")
    monkeypatch.setenv("s3-region", "us-east-1")
    monkeypatch.setenv("reportExpirationInDays", "7")
    config = load_config()
    assert config.enabled is True
    assert config.bucket == "automationtests"
    assert config.endpoint == "http://minio.mosip.net"
    assert config.expiration_days == 7
    # A custom endpoint implies path style addressing, which MinIO needs.
    assert config.path_style is True


def test_default_bucket_is_automationtests():
    assert load_config().bucket == DEFAULT_BUCKET


def test_disabled_by_default():
    assert load_config().enabled is False


def test_missing_settings_are_reported():
    config = load_config(cli={"push_reports_to_s3": "true"})
    assert "s3-user-key" in config.missing()
    assert "s3-account" not in config.missing()


def test_dry_run_reports_keys_without_network(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "results" / "nested").mkdir()
    (tmp_path / "results" / "nested" / "diff.json").write_text("{}", encoding="utf-8")

    config = S3Config(
        enabled=True,
        endpoint="http://minio:9000",
        bucket="automationtests",
        access_key="k",
        secret_key="s",
        path_style=True,
        prefix="conformance",
    )
    uploaded = upload_reports(config, [tmp_path / "results"], dry_run=True)
    keys = sorted(item["key"] for item in uploaded)
    assert keys == [
        "conformance/results/nested/diff.json",
        "conformance/results/results.json",
    ]


def test_run_id_is_appended_to_the_prefix(tmp_path):
    (tmp_path / "f.json").write_text("{}", encoding="utf-8")
    config = S3Config(
        endpoint="http://minio:9000", bucket="b", path_style=True, prefix="conformance"
    )
    config.run_id = "certify-1767225600"
    uploaded = upload_reports(config, [tmp_path / "f.json"], dry_run=True)
    assert uploaded[0]["key"] == "conformance/certify-1767225600/f.json"


def test_bool_parsing():
    for value in ("1", "true", "YES", "on", True):
        assert _as_bool(value) is True
    for value in ("0", "false", "no", "", None, False):
        assert _as_bool(value) is False


def test_config_file_is_loaded_and_cli_wins(tmp_path):
    path = tmp_path / "s3.json"
    path.write_text(
        json.dumps({"push_reports_to_s3": True, "s3_account": "from-file", "s3_region": "eu-west-1"}),
        encoding="utf-8",
    )
    config = load_config(cli={"s3_account": "from-cli"}, config_file=path)
    assert config.enabled is True
    assert config.bucket == "from-cli"
    assert config.region == "eu-west-1"
