"""Synchronous client for the OpenID Foundation conformance suite REST API.

Mirrors the create / run / poll / export flow used by scripts/run-test-plan.py
without requiring a full suite checkout. Official scripts can still be invoked
via --official-script.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import httpx


class ConformanceError(RuntimeError):
    pass


class OidfClient:
    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        if not base_url.endswith("/"):
            base_url += "/"
        self.base_url = base_url
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers,
            verify=verify_ssl,
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OidfClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise ConformanceError(
                f"{method} {path} failed HTTP {response.status_code}: {response.text[:500]}"
            )
        return response

    def wait_until_ready(self, timeout: int = 360) -> None:
        deadline = time.time() + timeout
        last_error = "not attempted"
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                response = self._client.get("api/plan", params={"length": "1"})
                if response.status_code == 200:
                    print(f"Conformance suite ready after {attempt} attempt(s)")
                    return
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            print(f"Suite not ready (attempt {attempt}): {last_error}")
            time.sleep(5)
        raise ConformanceError(f"Suite did not become ready within {timeout}s: {last_error}")

    def create_plan(self, plan_name: str, variant: dict, config: dict) -> dict:
        params = {"planName": plan_name, "variant": json.dumps(variant)}
        response = self._request(
            "POST",
            "api/plan",
            params=params,
            headers={"Content-Type": "application/json"},
            content=json.dumps(config),
        )
        if response.status_code not in (200, 201):
            raise ConformanceError(f"create plan failed: {response.status_code} {response.text[:500]}")
        return response.json()

    def get_plan(self, plan_id: str) -> dict:
        return self._request("GET", f"api/plan/{plan_id}").json()

    def start_module(self, plan_id: str, test_module: str, variant: Optional[dict] = None) -> dict:
        params = {"test": test_module, "plan": plan_id}
        if variant:
            params["variant"] = json.dumps(variant)
        return self._request("POST", "api/runner", params=params).json()

    def get_info(self, test_id: str) -> dict:
        return self._request("GET", f"api/info/{test_id}").json()

    def wait_for_finished(self, test_id: str, timeout: int = 600, poll: float = 3.0) -> dict:
        deadline = time.time() + timeout
        last: dict = {}
        while time.time() < deadline:
            last = self.get_info(test_id)
            status = (last.get("status") or last.get("state") or "").upper()
            if status in {"FINISHED", "INTERRUPTED"}:
                return last
            time.sleep(poll)
        raise ConformanceError(f"Timed out waiting for test {test_id}; last={last}")

    def export_html(self, plan_id: str, output_dir: Path) -> Optional[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            response = self._client.get(f"api/plan/exporthtml/{plan_id}")
            if response.status_code != 200:
                print(f"HTML export skipped: HTTP {response.status_code}")
                return None
            filename = _filename_from_disposition(response.headers.get("content-disposition"), f"{plan_id}.zip")
            path = output_dir / filename
            path.write_bytes(response.content)
            return path
        except Exception as exc:  # noqa: BLE001
            print(f"HTML export failed: {exc}")
            return None


def _filename_from_disposition(header: Optional[str], fallback: str) -> str:
    if not header:
        return fallback
    match = re.search(r'filename="?([^"]+)"?', header)
    return match.group(1) if match else fallback


def normalize_base_url(url: str) -> str:
    if not url:
        return url
    return url if url.endswith("/") else url + "/"


def public_url(base_url: str, path: str) -> str:
    return urljoin(normalize_base_url(base_url), path.lstrip("/"))
