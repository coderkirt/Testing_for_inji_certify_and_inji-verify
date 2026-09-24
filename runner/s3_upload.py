"""Publish conformance reports to the object store the api-testrig already uses.

The MOSIP api-testrig pushes reports with ``S3Adapter.java`` in
``apitest-commons``: after a run it calls the AWS S3 SDK's ``putObject`` using
these config keys (``ConfigManager.java``):

    push-reports-to-s3   on/off
    s3-host              endpoint (custom host for MinIO)
    s3-region
    s3-user-key
    s3-user-secret
    s3-account           bucket name - the api-testrig default is "automationtests"
    reportExpirationInDays

This module speaks the same config keys and writes to the same bucket, but
signs requests with a small SigV4 implementation instead of pulling in an SDK
(the runner is deliberately dependency-light: httpx and stdlib only).

Usage:

    python runner/s3_upload.py --source results/combined --prefix conformance/2026-09-24
    python runner/s3_upload.py --source results --dry-run

Config comes from CLI flags, then ``runner/configs/s3.json``, then environment
variables (either ``PUSH_REPORTS_TO_S3`` or ``push-reports-to-s3``).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote, urlsplit

import httpx

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"
DEFAULT_BUCKET = "automationtests"
DEFAULT_REGION = "us-east-1"
DEFAULT_PREFIX = "conformance"
# Same place the other run settings live. Missing is fine - the file is only a
# template until someone fills in credentials.
DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent / "configs" / "s3.json"

# Accepted spellings for each setting, in precedence order after CLI flags.
ENV_KEYS: dict[str, tuple[str, ...]] = {
    "push_reports_to_s3": ("PUSH_REPORTS_TO_S3", "push-reports-to-s3"),
    "s3_host": ("S3_HOST", "s3-host"),
    "s3_region": ("S3_REGION", "s3-region"),
    "s3_user_key": ("S3_USER_KEY", "s3-user-key", "AWS_ACCESS_KEY_ID"),
    "s3_user_secret": ("S3_USER_SECRET", "s3-user-secret", "AWS_SECRET_ACCESS_KEY"),
    "s3_account": ("S3_ACCOUNT", "s3-account", "S3_BUCKET"),
    "report_expiration_in_days": ("REPORT_EXPIRATION_IN_DAYS", "reportExpirationInDays"),
    "s3_path_style": ("S3_PATH_STYLE", "s3-path-style"),
    "s3_prefix": ("S3_PREFIX", "s3-prefix"),
}

TRUTHY = {"1", "true", "yes", "on", "y"}


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in TRUTHY


def _as_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


@dataclass
class S3Config:
    enabled: bool = False
    endpoint: str = ""
    region: str = DEFAULT_REGION
    access_key: str = ""
    secret_key: str = ""
    bucket: str = DEFAULT_BUCKET
    path_style: bool = True
    prefix: str = DEFAULT_PREFIX
    expiration_days: int = 30
    run_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def missing(self) -> list[str]:
        """Settings that must be present before an upload can be attempted."""
        problems = []
        if not self.access_key:
            problems.append("s3-user-key")
        if not self.secret_key:
            problems.append("s3-user-secret")
        if not self.bucket:
            problems.append("s3-account")
        return problems

    def base_url(self) -> str:
        if self.endpoint:
            return self.endpoint if "://" in self.endpoint else f"https://{self.endpoint}"
        return f"https://s3.{self.region}.amazonaws.com"


def load_config(
    cli: Optional[dict[str, Any]] = None,
    config_file: Optional[Path] = None,
) -> S3Config:
    """Resolve config with precedence cli > file > env."""
    values: dict[str, Any] = {}

    if config_file and config_file.exists():
        try:
            loaded = json.loads(config_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                values.update({k: v for k, v in loaded.items() if not k.startswith("_")})
        except json.JSONDecodeError as exc:
            print(f"Ignoring malformed {config_file}: {exc}")

    for field_name, names in ENV_KEYS.items():
        for name in names:
            if name in os.environ and os.environ[name] != "":
                values.setdefault(field_name, os.environ[name])

    for key, value in (cli or {}).items():
        if value is not None:
            values[key] = value

    enabled = _as_bool(values.get("push_reports_to_s3"), False)
    return S3Config(
        enabled=enabled,
        endpoint=str(values.get("s3_host") or ""),
        region=str(values.get("s3_region") or DEFAULT_REGION),
        access_key=str(values.get("s3_user_key") or ""),
        secret_key=str(values.get("s3_user_secret") or ""),
        bucket=str(values.get("s3_account") or DEFAULT_BUCKET),
        path_style=_as_bool(values.get("s3_path_style"), default=bool(values.get("s3_host"))),
        prefix=str(values.get("s3_prefix") or DEFAULT_PREFIX).strip("/"),
        expiration_days=_as_int(values.get("report_expiration_in_days"), 30),
    )


# --------------------------------------------------------------------- signing


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret_key: str, date_stamp: str, region: str, service: str = SERVICE) -> bytes:
    key = _hmac(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, "aws4_request")


def canonical_request(
    method: str,
    canonical_uri: str,
    canonical_query: str,
    headers: dict[str, str],
    payload_hash: str,
) -> tuple[str, str]:
    """Return ``(canonical_request, signed_headers)``."""
    lowered = {name.lower(): str(value).strip() for name, value in headers.items()}
    signed_headers = ";".join(sorted(lowered))
    canonical_headers = "".join(f"{name}:{lowered[name]}\n" for name in sorted(lowered))
    request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    return request, signed_headers


def sign_request(
    *,
    method: str,
    url: str,
    region: str,
    access_key: str,
    secret_key: str,
    payload: bytes = b"",
    headers: Optional[dict[str, str]] = None,
    service: str = SERVICE,
    now: Optional[datetime] = None,
    sign_payload_header: bool = True,
) -> dict[str, str]:
    """Return the headers (including Authorization) for one signed request.

    ``sign_payload_header`` adds ``x-amz-content-sha256``, which S3 requires
    for all non-TLS requests and accepts for TLS ones.
    """
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    parsed = urlsplit(url)
    # S3 canonical URIs are encoded once, per segment, with '/' preserved.
    canonical_uri = quote(parsed.path or "/", safe="/~")
    query_pairs = []
    if parsed.query:
        for pair in parsed.query.split("&"):
            name, _, value = pair.partition("=")
            query_pairs.append((quote(name, safe="~"), quote(value, safe="~")))
        query_pairs.sort()
    canonical_query = "&".join(f"{name}={value}" for name, value in query_pairs)

    payload_hash = _sha256_hex(payload)

    signed: dict[str, str] = {"host": parsed.netloc, "x-amz-date": amz_date}
    if sign_payload_header:
        signed["x-amz-content-sha256"] = payload_hash
    for name, value in (headers or {}).items():
        signed[name] = value

    canonical, signed_headers = canonical_request(
        method, canonical_uri, canonical_query, signed, payload_hash
    )
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, _sha256_hex(canonical.encode("utf-8"))]
    )
    signature = hmac.new(
        signing_key(secret_key, date_stamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    result = dict(headers or {})
    result["x-amz-date"] = amz_date
    if sign_payload_header:
        result["x-amz-content-sha256"] = payload_hash
    result["Authorization"] = (
        f"{ALGORITHM} Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return result


# --------------------------------------------------------------------- upload


def object_url(config: S3Config, key: str) -> str:
    base = config.base_url().rstrip("/")
    if config.path_style:
        return f"{base}/{config.bucket}/{quote(key, safe='/~')}"
    host = urlsplit(base).netloc
    scheme = urlsplit(base).scheme or "https"
    return f"{scheme}://{config.bucket}.{host}/{quote(key, safe='/~')}"


def put_object(
    config: S3Config,
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    verify_ssl: bool = True,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """PUT one object. Returns a small record describing the upload."""
    url = object_url(config, key)
    extra_headers = {"content-type": content_type}
    headers = sign_request(
        method="PUT",
        url=url,
        region=config.region,
        access_key=config.access_key,
        secret_key=config.secret_key,
        payload=data,
        headers=extra_headers,
    )
    with httpx.Client(verify=verify_ssl, timeout=timeout) as client:
        response = client.put(url, content=data, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(
            f"S3 PUT {key} failed HTTP {response.status_code}: {response.text[:300]}"
        )
    return {"key": key, "bytes": len(data), "url": url}


def iter_files(sources: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for source in sources:
        if source.is_file():
            files.append(source)
        elif source.is_dir():
            files.extend(sorted(p for p in source.rglob("*") if p.is_file()))
    return files


def object_key(source: Path, path: Path) -> str:
    """Object key for one file, relative to the source it came from.

    Keys must never embed an absolute filesystem path (a Windows temp path in
    the bucket would be useless), so a directory source keeps only its own
    name plus the relative path inside it.
    """
    if source.is_file():
        return source.name
    try:
        return path.relative_to(source.parent).as_posix()
    except ValueError:
        return f"{source.name}/{path.name}"


def upload_reports(
    config: S3Config,
    sources: Iterable[Path],
    prefix: Optional[str] = None,
    verify_ssl: bool = True,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Upload every file under ``sources`` to ``<prefix>/<relative path>``."""
    root_prefix = (prefix or config.prefix).strip("/")
    if config.run_id:
        root_prefix = f"{root_prefix}/{config.run_id}" if root_prefix else config.run_id
    uploaded: list[dict[str, Any]] = []
    for source in sources:
        for path in iter_files([source]):
            relative = object_key(source, path)
            key = f"{root_prefix}/{relative}" if root_prefix else relative
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            data = path.read_bytes()
            if dry_run:
                uploaded.append({"key": key, "bytes": len(data), "url": object_url(config, key)})
                continue
            uploaded.append(put_object(config, key, data, content_type, verify_ssl=verify_ssl))
    return uploaded


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish conformance reports to S3/MinIO")
    parser.add_argument("--source", action="append", default=[], type=Path)
    parser.add_argument("--prefix")
    parser.add_argument("--run-id")
    parser.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--endpoint")
    parser.add_argument("--region")
    parser.add_argument("--access-key")
    parser.add_argument("--secret-key")
    parser.add_argument("--bucket")
    parser.add_argument("--push", choices=["true", "false"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    config = load_config(
        cli={
            "s3_host": args.endpoint,
            "s3_region": args.region,
            "s3_user_key": args.access_key,
            "s3_user_secret": args.secret_key,
            "s3_account": args.bucket,
            "push_reports_to_s3": args.push,
            "s3_prefix": args.prefix,
        },
        config_file=args.config_file,
    )
    config.run_id = args.run_id or config.run_id

    if not args.source:
        print("No --source given; nothing to publish")
        return 0

    if not config.enabled:
        print("push-reports-to-s3 is off - skipping report publish")
        return 0

    problems = config.missing()
    if problems and not args.dry_run:
        print(f"Report publish requested but missing: {', '.join(problems)}", file=sys.stderr)
        return 2

    try:
        uploaded = upload_reports(
            config,
            args.source,
            prefix=args.prefix,
            verify_ssl=not args.insecure,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - report publish must not mask the run result
        print(f"Report publish failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "bucket": config.bucket,
                "prefix": args.prefix or config.prefix,
                "files": len(uploaded),
                "dryRun": args.dry_run,
                "objects": uploaded[:20],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
