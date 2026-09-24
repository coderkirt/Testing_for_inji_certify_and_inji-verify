"""Client level behaviour: handoff, timeouts, explicit start.

The original client polled api/info until FINISHED/INTERRUPTED and raised on
anything else, so a module waiting on a wallet handoff burned the full module
timeout and then killed the whole plan. These tests pin the replacement.
"""

from __future__ import annotations

import json

import pytest

from oidf_client import ConformanceTimeout, OidfClient, PlanCreateError


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""
        self.headers = {}
        self.content = self.text.encode()

    def json(self):
        return self._payload


class FakeTransport:
    """Minimal stand-in for httpx.Client."""

    def __init__(self, info_sequence=None, info_by_id=None, fail_plan=None):
        self.info_sequence = list(info_sequence or [])
        self.info_by_id = info_by_id or {}
        self.fail_plan = fail_plan
        self.calls = []
        # A real module keeps reporting its current state, so once the scripted
        # sequence is exhausted the last response is repeated.
        self._last_info = {"status": "UNKNOWN"}

    def request(self, method, path, **kwargs):
        return self._route(method, path, kwargs)

    def get(self, path, **kwargs):
        return self._route("GET", path, kwargs)

    def post(self, path, **kwargs):
        return self._route("POST", path, kwargs)

    def _route(self, method, path, kwargs, **_ignored):
        self.calls.append((method, path))
        if path.startswith("api/plan") and method == "POST":
            if self.fail_plan:
                return FakeResponse(400, {"error": self.fail_plan})
            plan = json.loads(json.dumps(PLAN))
            return FakeResponse(201, plan)
        if path.startswith("api/info/"):
            if self.info_sequence:
                self._last_info = self.info_sequence.pop(0)
            return FakeResponse(200, self._last_info)
        if path.startswith("api/log/"):
            return FakeResponse(200, [])
        if method == "POST" and path.startswith("api/runner"):
            return FakeResponse(201, {"id": "started-module"})
        if method == "POST":
            return FakeResponse(200, {"id": path.rsplit("/", 1)[-1]})
        return FakeResponse(200, {})

    def paths(self, method=None):
        return [path for m, path in self.calls if method is None or m == method]


PLAN = {
    "id": "plan-1",
    "modules": [{"testModule": "mod", "variant": {"credential_format": "sd_jwt_vc"}}],
}


def make_client(transport):
    client = OidfClient("https://localhost.emobix.co.uk:8443/", verify_ssl=False)
    client._client = transport
    return client


def test_finished_module_settles():
    transport = FakeTransport([{"status": "RUNNING"}, {"status": "FINISHED", "result": "PASSED"}])
    client = make_client(transport)
    outcome, info = client.wait_for_settled("m", timeout=5, poll=0)
    assert outcome == "FINISHED"
    assert info["result"] == "PASSED"


def test_handoff_returns_immediately_instead_of_hanging():
    transport = FakeTransport([{"status": "WAITING"}])
    client = make_client(transport)
    outcome, info = client.wait_for_settled("m", timeout=600, poll=0, handoff_grace=0)
    assert outcome == "WAITING"
    assert info["status"] == "WAITING"
    # It must not have polled 600 seconds worth of times.
    assert len(transport.paths("GET")) == 1


def test_handoff_grace_keeps_polling_then_gives_up():
    transport = FakeTransport([{"status": "WAITING"}, {"status": "WAITING"}])
    client = make_client(transport)
    outcome, _ = client.wait_for_settled("m", timeout=600, poll=0, handoff_grace=0.05)
    assert outcome == "WAITING"
    assert len(transport.paths("GET")) >= 2


def test_running_module_past_the_deadline_times_out():
    transport = FakeTransport([{"status": "RUNNING"}])
    client = make_client(transport)
    outcome, _ = client.wait_for_settled("m", timeout=0, poll=0)
    assert outcome == "TIMEOUT"


def test_configured_module_is_started_explicitly_when_auto_start_is_on():
    transport = FakeTransport(
        [{"status": "CONFIGURED"}, {"status": "FINISHED", "result": "PASSED"}]
    )
    client = make_client(transport)
    outcome, _ = client.wait_for_settled("m", timeout=5, poll=0, auto_start=True)
    assert outcome == "FINISHED"
    assert client.base_url  # sanity
    assert transport.paths("POST") == ["api/runner/m"]


def test_configured_module_is_reported_when_auto_start_is_off():
    transport = FakeTransport([{"status": "CONFIGURED"}])
    client = make_client(transport)
    outcome, _ = client.wait_for_settled("m", timeout=0, poll=0, auto_start=False)
    assert outcome == "CONFIGURED"
    assert transport.paths("POST") == []


def test_interrupted_is_terminal():
    transport = FakeTransport([{"status": "INTERRUPTED", "result": "INTERRUPTED"}])
    client = make_client(transport)
    outcome, _ = client.wait_for_settled("m", timeout=5, poll=0)
    assert outcome == "INTERRUPTED"


def test_wait_for_state_raises_a_timeout_not_a_generic_error():
    transport = FakeTransport([{"status": "RUNNING"}])
    client = make_client(transport)
    with pytest.raises(ConformanceTimeout):
        client.wait_for_state("m", {"FINISHED"}, timeout=0, poll=0)


def test_create_plan_surfaces_the_suite_error_message():
    transport = FakeTransport(fail_plan="Unknown test plan")
    client = make_client(transport)
    with pytest.raises(PlanCreateError) as error:
        client.create_plan("bad-plan", {}, {})
    assert "Unknown test plan" in str(error.value)


def test_plan_modules_tolerates_a_plan_without_modules():
    transport = FakeTransport(info_by_id={}, info_sequence=[])
    client = make_client(transport)
    assert client.plan_modules({"id": "plan-1"}) == []


def test_plan_modules_reads_the_create_response_directly():
    transport = FakeTransport()
    client = make_client(transport)
    assert len(client.plan_modules(dict(PLAN))) == 1


def test_module_result_and_state_helpers():
    assert OidfClient.module_state({"status": "FINISHED"}) == "FINISHED"
    assert OidfClient.module_state({"state": "waiting"}) == "WAITING"
    assert OidfClient.module_result({"result": "passed"}) == "PASSED"
    assert OidfClient.module_result({}) == ""
