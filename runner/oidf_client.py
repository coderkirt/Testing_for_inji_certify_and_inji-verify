"""Synchronous client for the OpenID Foundation conformance suite REST API.

Mirrors the create / configure / start / poll / export flow used by
scripts/run-test-plan.py without requiring a full suite checkout. Official
scripts can still be invoked via --official-script.

Endpoint reference (verified against scripts/conformance.py):

    POST api/plan?planName=&variant=      create a plan            -> 201
    GET  api/plan/{id}                    plan + module list       -> 200
    GET  api/plan/available               plans + variants         -> 200
    POST api/runner?test=&plan=&variant=  create a module instance -> 201
    POST api/runner/{id}                  start a created module   -> 200
    GET  api/info/{id}                    module status/result     -> 200
    GET  api/log/{id}                     per-condition log        -> 200
    GET  api/plan/exporthtml/{id}         HTML result zip          -> 200
    GET  api/plan/export/{id}             JSON result zip          -> 200
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

# Module status values used by the suite (AbstractTestModule.Status plus the
# skill's own terminal handling in run-test-plan.py).
TERMINAL_STATES = frozenset({"FINISHED", "INTERRUPTED"})
HANDOFF_STATES = frozenset({"WAITING"})
STARTABLE_STATES = frozenset({"CONFIGURED"})

# Result values the suite reports on api/info.
PASS_RESULTS = frozenset({"PASSED", "PASSED_WITH_WARNINGS", "WARNING", "REVIEW"})
FAIL_RESULTS = frozenset({"FAILED", "FAILURE", "INTERRUPTED"})
SKIP_RESULTS = frozenset({"SKIPPED", "SKIP", "NOT_RUN"})


class ConformanceError(RuntimeError):
    """Transport or protocol level failure talking to the suite."""


class ConformanceTimeout(ConformanceError):
    """The suite never moved a module out of a non-terminal state."""


class PlanCreateError(ConformanceError):
    """POST api/plan was rejected (usually a bad plan name or variant)."""


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

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        """Prefer the suite's own error text over a bare HTTP status."""
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - non JSON error body
            return f"HTTP {response.status_code} {response.text[:300]}"
        if isinstance(body, dict):
            message = body.get("error") or body.get("message")
            if message:
                return f"HTTP {response.status_code} {message}"
        return f"HTTP {response.status_code} {response.text[:300]}"

    # ------------------------------------------------------------------ suite

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
            except Exception as exc:  # noqa: BLE001 - retry every transport error
                last_error = str(exc)
            print(f"Suite not ready (attempt {attempt}): {last_error}")
            time.sleep(5)
        raise ConformanceError(f"Suite did not become ready within {timeout}s: {last_error}")

    def available_plans(self) -> dict[str, Any]:
        """GET api/plan/available - used to validate plan names/variants early."""
        return self._request("GET", "api/plan/available").json()

    # ------------------------------------------------------------------- plans

    def create_plan(self, plan_name: str, variant: dict, config: dict) -> dict:
        params = {"planName": plan_name, "variant": json.dumps(variant)}
        response = self._client.post(
            "api/plan",
            params=params,
            headers={"Content-Type": "application/json"},
            content=json.dumps(config),
        )
        if response.status_code not in (200, 201):
            raise PlanCreateError(
                f"create plan '{plan_name}' failed: {self._error_message(response)}"
            )
        return response.json()

    def get_plan(self, plan_id: str) -> dict:
        return self._request("GET", f"api/plan/{plan_id}").json()

    # ----------------------------------------------------------------- modules

    def plan_modules(self, plan: dict) -> list[dict]:
        """Modules of a plan, tolerating both create-plan and get-plan shapes."""
        modules = plan.get("modules")
        if modules:
            return modules
        plan_id = plan.get("id") or plan.get("planId")
        if plan_id:
            return self.get_plan(plan_id).get("modules") or []
        return []

    def start_module(self, plan_id: str, test_module: str, variant: Optional[dict] = None) -> dict:
        """Create a module instance from a plan. Does not start it."""
        params = {"test": test_module, "plan": plan_id}
        if variant:
            params["variant"] = json.dumps(variant)
        response = self._client.post("api/runner", params=params)
        if response.status_code not in (200, 201):
            raise ConformanceError(
                f"create module '{test_module}' failed: {self._error_message(response)}"
            )
        return response.json()

    def start_test(self, test_id: str) -> dict:
        """POST api/runner/{id} - start a module sitting in CONFIGURED.

        run-test-plan.py performs this step for modules that do not auto-start
        (for example oidcc-server-rotate-keys). Without it such a module parks
        in CONFIGURED until the caller gives up.
        """
        response = self._client.post(f"api/runner/{test_id}")
        if response.status_code not in (200, 201):
            raise ConformanceError(
                f"start test '{test_id}' failed: {self._error_message(response)}"
            )
        return response.json()

    def get_info(self, test_id: str) -> dict:
        return self._request("GET", f"api/info/{test_id}").json()

    def get_log(self, test_id: str) -> list[dict]:
        return self._request("GET", f"api/log/{test_id}").json()

    @staticmethod
    def module_state(info: dict) -> str:
        return (info.get("status") or info.get("state") or "").upper()

    @staticmethod
    def module_result(info: dict) -> str:
        return str(info.get("result") or info.get("testResult") or "").upper()

    def wait_for_state(
        self,
        test_id: str,
        states: frozenset[str] | set[str],
        timeout: int,
        poll: float = 3.0,
    ) -> tuple[str, dict]:
        """Poll api/info until the module reaches one of ``states``.

        Returns ``(state, info)``. Raises ConformanceTimeout if the deadline
        passes first - the caller turns that into a FAIL rather than a crash.
        """
        deadline = time.time() + timeout
        last: dict = {}
        while True:
            last = self.get_info(test_id)
            state = self.module_state(last)
            if state in states:
                return state, last
            if time.time() >= deadline:
                raise ConformanceTimeout(
                    f"module {test_id} still {state or 'unknown'} after {timeout}s"
                )
            time.sleep(poll)

    def wait_for_settled(
        self,
        test_id: str,
        timeout: int,
        poll: float = 3.0,
        handoff_grace: float = 0.0,
        auto_start: bool = False,
    ) -> tuple[str, dict]:
        """Wait for a module to reach a terminal state.

        Returns ``(outcome, info)`` where outcome is one of FINISHED,
        INTERRUPTED, WAITING, CONFIGURED or TIMEOUT.

        * WAITING means the suite is blocked on a human/mobile wallet handoff.
          Returning immediately (handoff_grace=0) lets the runner record a
          documented SKIP instead of burning the whole module timeout.
        * CONFIGURED means the module never auto-started; with auto_start the
          client POSTs api/runner/{id} and keeps waiting.
        """
        deadline = time.time() + timeout
        handoff_deadline: Optional[float] = None
        last: dict = {}
        started = False
        while True:
            last = self.get_info(test_id)
            state = self.module_state(last)
            if state in TERMINAL_STATES:
                return state, last
            if state in HANDOFF_STATES:
                if handoff_deadline is None:
                    handoff_deadline = time.time() + handoff_grace
                if time.time() >= handoff_deadline:
                    return "WAITING", last
            elif state in STARTABLE_STATES and auto_start and not started:
                print(f"Module {test_id} is CONFIGURED - starting it explicitly")
                try:
                    self.start_test(test_id)
                    started = True
                except ConformanceError as exc:
                    print(f"Could not start {test_id}: {exc}")
                    return "CONFIGURED", last
            if time.time() >= deadline:
                # A module that never left CONFIGURED was never started. Report
                # that distinctly from a module that ran and overran.
                if state in STARTABLE_STATES and not started:
                    return "CONFIGURED", last
                return "TIMEOUT", last
            time.sleep(poll)

    # ----------------------------------------------------------------- exports

    def export_html(self, plan_id: str, output_dir: Path) -> Optional[Path]:
        return self._export("exporthtml", plan_id, output_dir, f"{plan_id}.zip")

    def export_json(self, plan_id: str, output_dir: Path) -> Optional[Path]:
        """Signed JSON result zip - cheaper server side than exporthtml.

        Prefer this for CI; it is what run-test-plan.py uses for machine
        readable output.
        """
        return self._export("export", plan_id, output_dir, f"{plan_id}.json.zip")

    def _export(self, kind: str, plan_id: str, output_dir: Path, fallback: str) -> Optional[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            response = self._client.get(f"api/plan/{kind}/{plan_id}")
            if response.status_code != 200:
                print(f"{kind} export skipped: HTTP {response.status_code}")
                return None
            filename = _filename_from_disposition(
                response.headers.get("content-disposition"), fallback
            )
            path = output_dir / filename
            path.write_bytes(response.content)
            return path
        except Exception as exc:  # noqa: BLE001 - export is best effort
            print(f"{kind} export failed: {exc}")
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
