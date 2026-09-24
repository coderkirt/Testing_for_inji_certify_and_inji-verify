"""End to end: run the real orchestrator against a stub conformance suite.

This is the test that would have caught the original defects without Docker:

* a module parked in WAITING used to burn the full module timeout and then
  abort the whole plan, so the handoff test asserts a SKIP with a short
  timeout - if handoff handling regresses this fails instead of hanging;
* a module reporting PASSED while emitting failing conditions used to be a
  clean green, so there is an explicit test for the non-green outcome;
* the benchmark used to reject a healthy run containing a documented skip.

The stub implements the same REST surface as the suite (create plan, create
module, start module, info, log, export) with scripted per-module states.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import run_conformance

CERTIFY_PLAN = "oid4vci-1_0-issuer-test-plan"
VERIFY_PLAN = "oid4vp-1final-verifier-haip-test-plan"

PASSING_LOG = [
    {"startBlock": True, "src": "-START-BLOCK-", "blockId": "b1", "msg": "Credential Issuer metadata"},
    {"result": "SUCCESS", "src": "VCIGetDynamicCredentialIssuerMetadata", "blockId": "b1"},
]

# A module that satisfies the checker's top level result but has a failing
# condition inside it.
FAILURE_LOG = PASSING_LOG + [
    {"result": "FAILURE", "src": "UnexpectedConditionFailure", "blockId": "b1"},
]

CERTIFY_SCRIPT = {
    "oid4vci-1_0-issuer-metadata": [("RUNNING", None), ("FINISHED", "PASSED")],
    "oid4vci-1_0-issuer-happy-flow": [("FINISHED", "PASSED")],
    "oid4vci-1_0-issuer-deferred-issuance": [("WAITING", None)],
}

VERIFY_SCRIPT = {
    "oid4vp-1final-verifier-metadata": [("FINISHED", "PASSED")],
    "oid4vp-1final-verifier-happy-flow": [("WAITING", None)],
}

SCRIPTS = {CERTIFY_PLAN: CERTIFY_SCRIPT, VERIFY_PLAN: VERIFY_SCRIPT}


class StubSuiteHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _zip(self, filename: str) -> None:
        body = b"PK\x03\x04stub-export"
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parts = urlsplit(self.path)
        path = parts.path
        suite: "StubSuite" = self.server  # type: ignore[assignment]

        if path == "/api/plan":
            return self._json(200, {"plans": []})
        if path == "/api/plan/available":
            return self._json(200, suite.available())
        if path.startswith("/api/plan/exporthtml/"):
            return self._zip("plan-export-html.zip")
        if path.startswith("/api/plan/export/"):
            return self._zip("plan-export.zip")
        if path.startswith("/api/info/"):
            return self._json(200, suite.info_for(path.rsplit("/", 1)[-1]))
        if path.startswith("/api/log/"):
            return self._json(200, suite.log_for(path.rsplit("/", 1)[-1]))
        if path.startswith("/api/plan/"):
            plan_id = path.rsplit("/", 1)[-1]
            return self._json(200, suite.plans.get(plan_id, {"id": plan_id, "modules": []}))
        return self._json(404, {"error": f"no route for GET {path}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parts = urlsplit(self.path)
        path = parts.path
        params = {key: value[0] for key, value in parse_qs(parts.query).items()}
        suite: "StubSuite" = self.server  # type: ignore[assignment]

        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        if path == "/api/plan":
            plan_name = params.get("planName")
            if plan_name not in SCRIPTS:
                return self._json(400, {"error": f"Unknown test plan {plan_name}"})
            return self._json(201, suite.create_plan(plan_name))
        if path == "/api/runner":
            return self._json(201, {"id": suite.create_module(params.get("test") or "")})
        if path.startswith("/api/runner/"):
            suite.started.append(path.rsplit("/", 1)[-1])
            return self._json(200, {"status": "RUNNING"})
        return self._json(404, {"error": f"no route for POST {path}"})


class StubSuite(ThreadingHTTPServer):
    def __init__(self, script_overrides=None, log_overrides=None):
        super().__init__(("127.0.0.1", 0), StubSuiteHandler)
        self.script_overrides = script_overrides or {}
        self.log_overrides = log_overrides or {}
        self.counter = 0
        self.modules: dict[str, str] = {}
        self.positions: dict[str, int] = {}
        self.plans: dict[str, dict] = {}
        self.started: list[str] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/"

    def script_for(self, plan_name: str) -> dict:
        script = dict(SCRIPTS.get(plan_name, {}))
        script.update(self.script_overrides)
        return script

    def create_plan(self, plan_name: str) -> dict:
        plan_id = f"plan-{len(self.plans) + 1}"
        modules = [
            {"testModule": name, "variant": {"credential_format": "sd_jwt_vc"}}
            for name in self.script_for(plan_name)
        ]
        plan = {"id": plan_id, "planName": plan_name, "modules": modules}
        self.plans[plan_id] = plan
        return plan

    def create_module(self, test_module: str) -> str:
        self.counter += 1
        test_id = f"t{self.counter}"
        self.modules[test_id] = test_module
        return test_id

    def plan_name_for_module(self, test_module: str) -> str:
        for plan_name, script in SCRIPTS.items():
            if test_module in script:
                return plan_name
        return ""

    def info_for(self, test_id: str) -> dict:
        name = self.modules.get(test_id, "")
        plan_name = self.plan_name_for_module(name)
        sequence = self.script_for(plan_name).get(name) or [("FINISHED", "PASSED")]
        index = min(self.positions.get(name, 0), len(sequence) - 1)
        self.positions[name] = index + 1
        status, result = sequence[index]
        info = {
            "id": test_id,
            "testName": name,
            "status": status,
            "variant": {"credential_format": "sd_jwt_vc"},
        }
        if result:
            info["result"] = result
        return info

    def log_for(self, test_id: str) -> list:
        name = self.modules.get(test_id, "")
        return self.log_overrides.get(name, PASSING_LOG)

    def available(self) -> dict:
        return {
            "plans": [
                {
                    "planName": CERTIFY_PLAN,
                    "variant": {
                        "credential_format": ["sd_jwt_vc", "mdoc"],
                        "client_auth_type": ["private_key_jwt", "mtls"],
                        "fapi_profile": ["plain_fapi", "vci"],
                        "fapi_request_method": ["unsigned"],
                        "sender_constrain": ["dpop", "mtls"],
                        "fapi_response_mode": ["plain_response"],
                        "openid": ["openid_connect"],
                    },
                },
                {
                    "planName": VERIFY_PLAN,
                    "variant": {
                        "credential_format": ["sd_jwt_vc"],
                        "response_mode": ["direct_post.jwt"],
                    },
                },
            ]
        }


@pytest.fixture
def suite():
    servers: list[StubSuite] = []

    def _make(**kwargs) -> StubSuite:
        server = StubSuite(**kwargs)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server

    yield _make

    for server in servers:
        server.shutdown()
        server.server_close()


def run_cli(tmp_path: Path, suite: StubSuite, *extra: str) -> tuple[int, dict]:
    output = tmp_path / "results"
    code = run_conformance.main(
        [
            "--suite-url",
            suite.url,
            "--output-dir",
            str(output),
            # Short timeout: a handoff module must be skipped promptly, not
            # waited out. If that regresses, the module maps to FAIL.
            "--module-timeout",
            "3",
            *extra,
        ]
    )
    return code, json.loads((output / "results.json").read_text(encoding="utf-8"))


def modules_of(document: dict, component: str) -> dict[str, dict]:
    for plan in document["plans"]:
        if plan["component"] == component:
            return {module["testModule"]: module for module in plan["modules"]}
    raise AssertionError(f"no plan for {component} in {document['plans']}")


def test_certify_run_passes_and_skips_the_handoff(suite, tmp_path):
    code, document = run_cli(tmp_path, suite(), "--component", "certify")

    assert code == 0
    assert document["benchmarkMet"] is True, document["benchmarkReasons"]
    modules = modules_of(document, "certify")
    assert modules["oid4vci-1_0-issuer-metadata"]["mapped"] == "PASS"
    assert modules["oid4vci-1_0-issuer-happy-flow"]["mapped"] == "PASS"

    handoff = modules["oid4vci-1_0-issuer-deferred-issuance"]
    assert handoff["mapped"] == "SKIP"
    assert handoff["handoff"] is True
    assert "handoff" in handoff["reason"]

    assert document["summary"]["handoffSkips"] == 1
    assert document["summary"]["unexpectedFailures"] == 0
    assert document["summary"]["unexpectedSkips"] == 0
    assert document["summary"]["adjudicatedModules"] == 2


def test_run_writes_exports_and_a_report_for_every_plan(suite, tmp_path):
    _, document = run_cli(tmp_path, suite(), "--component", "certify")
    plan = document["plans"][0]
    assert plan["planId"]
    # Exports land per component, results.json lands in --output-dir.
    assert plan["exportHtml"] and Path(plan["exportHtml"]).exists()
    assert plan["exportJson"] and Path(plan["exportJson"]).exists()
    assert Path(plan["exportHtml"]).parent == tmp_path / "results" / "certify"
    assert (tmp_path / "results" / "results.json").exists()
    assert (tmp_path / "results" / "certify" / "plan-export-html.zip").exists()


def test_unexpected_failure_fails_the_run(suite, tmp_path):
    stub = suite(script_overrides={"oid4vci-1_0-issuer-happy-flow": [("FINISHED", "FAILED")]})
    code, document = run_cli(tmp_path, stub, "--component", "certify")

    assert code == 1
    assert document["benchmarkMet"] is False
    modules = modules_of(document, "certify")
    assert modules["oid4vci-1_0-issuer-happy-flow"]["mapped"] == "FAIL"
    assert document["summary"]["unexpectedFailures"] == 1
    assert "unexpected failure" in " ".join(document["benchmarkReasons"])


def test_module_passing_with_failing_conditions_is_not_green(suite, tmp_path):
    """The false green the original harness could produce."""
    stub = suite(log_overrides={"oid4vci-1_0-issuer-metadata": FAILURE_LOG})
    code, document = run_cli(tmp_path, stub, "--component", "certify")

    modules = modules_of(document, "certify")
    metadata = modules["oid4vci-1_0-issuer-metadata"]
    # The module itself still reports PASSED...
    assert metadata["result"] == "PASSED"
    assert metadata["mapped"] == "PASS"
    # ...but the failing condition inside it is counted and fails the gate.
    assert metadata["unexpectedFailures"] == [
        {"current_block": "Credential Issuer metadata", "src": "UnexpectedConditionFailure"}
    ]
    assert document["summary"]["conditionUnexpectedFailures"] == 1
    assert code == 1
    assert document["benchmarkMet"] is False


def test_documented_expected_failure_is_tolerated(suite, tmp_path):
    stub = suite(script_overrides={"oid4vci-1_0-issuer-happy-flow": [("FINISHED", "FAILED")]})
    expected = tmp_path / "expected-failures.json"
    expected.write_text(
        json.dumps(
            {
                "modules": {
                    "oid4vci-1_0-issuer-happy-flow": "known gap tracked in ISSUE-123"
                }
            }
        ),
        encoding="utf-8",
    )
    code, document = run_cli(
        tmp_path, stub, "--component", "certify", "--expected-failures", str(expected)
    )

    module = modules_of(document, "certify")["oid4vci-1_0-issuer-happy-flow"]
    assert module["mapped"] == "SKIP"
    assert module["expectedFailure"] is True
    assert document["summary"]["toleratedFailures"] == 1
    assert document["benchmarkMet"] is True, document["benchmarkReasons"]


def test_condition_level_expected_failure_via_the_oidf_schema(suite, tmp_path):
    stub = suite(
        script_overrides={"oid4vci-1_0-issuer-metadata": [("FINISHED", "FAILED")]},
        log_overrides={"oid4vci-1_0-issuer-metadata": FAILURE_LOG},
    )
    expected = tmp_path / "expected-failures.json"
    expected.write_text(
        json.dumps(
            {
                "conditions": [
                    {
                        "test-name": "oid4vci-1_0-issuer-metadata",
                        "configuration-filename": "issuer-plan.json",
                        "variant": "*",
                        "current-block": "Credential Issuer metadata",
                        "condition": "UnexpectedConditionFailure",
                        "expected-result": "failure",
                        "comment": "signature suite pending",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    code, document = run_cli(
        tmp_path, stub, "--component", "certify", "--expected-failures", str(expected)
    )

    module = modules_of(document, "certify")["oid4vci-1_0-issuer-metadata"]
    assert module["unexpectedFailures"] == []
    assert module["expectedFailures"] == [
        {"current_block": "Credential Issuer metadata", "src": "UnexpectedConditionFailure"}
    ]
    # Every failing condition is covered, so the module becomes a documented
    # skip instead of a regression - the point of the OIDF schema.
    assert module["mapped"] == "SKIP"
    assert module["expectedFailure"] is True
    assert document["summary"]["unexpectedFailures"] == 0
    assert document["summary"]["toleratedFailures"] == 1
    assert code == 0, document["benchmarkReasons"]


def test_listed_expected_skip_is_never_started(suite, tmp_path):
    stub = suite()
    skips = tmp_path / "expected-skips.json"
    skips.write_text(
        json.dumps({"modules": ["oid4vci-1_0-issuer-happy-flow"]}), encoding="utf-8"
    )
    _, document = run_cli(
        tmp_path, stub, "--component", "certify", "--expected-skips", str(skips)
    )
    module = modules_of(document, "certify")["oid4vci-1_0-issuer-happy-flow"]
    assert module["mapped"] == "SKIP"
    assert module["expectedSkip"] is True
    assert module["testId"] is None
    # Never created, so never started.
    assert stub.started == []


def test_combined_run_covers_both_components(suite, tmp_path):
    code, document = run_cli(tmp_path, suite(), "--combined")

    assert document["mode"] == "combined"
    assert {plan["component"] for plan in document["plans"]} == {"certify", "verify"}
    assert modules_of(document, "verify")["oid4vp-1final-verifier-happy-flow"]["handoff"] is True
    assert code == 0, document["benchmarkReasons"]


def test_combined_run_fails_when_one_component_regresses(suite, tmp_path):
    stub = suite(script_overrides={"oid4vp-1final-verifier-metadata": [("FINISHED", "FAILED")]})
    code, document = run_cli(tmp_path, stub, "--combined")
    assert code == 1
    assert modules_of(document, "verify")["oid4vp-1final-verifier-metadata"]["mapped"] == "FAIL"


def test_validate_plans_checks_against_the_running_suite(suite, tmp_path, capsys):
    code = run_conformance.main(
        [
            "--suite-url",
            suite().url,
            "--component",
            "certify",
            "--output-dir",
            str(tmp_path / "results"),
            "--validate-plans",
        ]
    )
    assert code == 0
    captured = capsys.readouterr().out
    assert CERTIFY_PLAN in captured
    assert "variant dimension(s) offered" in captured


def test_validate_plans_reports_a_plan_the_suite_does_not_offer(suite, tmp_path, monkeypatch):
    monkeypatch.setattr(
        run_conformance, "plan_context", lambda meta, mapping: {
            "planName": "totally-unknown-plan",
            "component": meta.get("component", "certify"),
            "role": meta.get("role"),
            "configFile": meta["configFile"],
            "variant": {"a": "b"},
            "config": {},
            "alias": None,
        }
    )
    code = run_conformance.main(
        [
            "--suite-url",
            suite().url,
            "--component",
            "certify",
            "--output-dir",
            str(tmp_path / "results"),
            "--validate-plans",
        ]
    )
    assert code == 1


def test_only_filter_runs_the_selected_module_and_reports_the_rest(suite, tmp_path):
    """Selective execution must not make a partial run look like a full one."""
    stub = suite()
    code, document = run_cli(
        tmp_path, stub, "--component", "certify", "--only", "*issuer-metadata*"
    )

    modules = modules_of(document, "certify")
    assert modules["oid4vci-1_0-issuer-metadata"]["mapped"] == "PASS"
    for name in ("oid4vci-1_0-issuer-happy-flow", "oid4vci-1_0-issuer-deferred-issuance"):
        assert modules[name]["mapped"] == "SKIP"
        assert modules[name]["filtered"] is True
        assert modules[name]["outcome"] == "FILTERED"
        assert "--only" in modules[name]["reason"]

    # Only the selected module was ever instantiated in the suite: a filtered
    # module is not created and therefore cannot be started by accident.
    assert len(stub.modules) == 1
    # A filtered module never ran, so it cannot be counted as a module that ran.
    assert document["summary"]["ranModules"] == ["oid4vci-1_0-issuer-metadata"]
    assert document["summary"]["filtered"] == 2
    assert document["selection"] == {"only": ["*issuer-metadata*"], "skip": []}
    assert code == 0, document["benchmarkReasons"]


def test_skip_filter_excludes_matching_modules(suite, tmp_path):
    stub = suite()
    _, document = run_cli(
        tmp_path, stub, "--component", "certify", "--skip", "*deferred*,*happy*"
    )

    modules = modules_of(document, "certify")
    assert modules["oid4vci-1_0-issuer-metadata"]["mapped"] == "PASS"
    assert modules["oid4vci-1_0-issuer-happy-flow"]["filtered"] is True
    assert modules["oid4vci-1_0-issuer-deferred-issuance"]["filtered"] is True
    # The comma separated form was split into two patterns.
    assert document["selection"]["skip"] == ["*deferred*", "*happy*"]
    assert document["summary"]["handoffSkips"] == 0


def test_a_filtered_required_module_fails_the_gate(suite, tmp_path):
    """Selective execution cannot quietly drop a module the benchmark requires."""
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(
        json.dumps({"requiredModules": ["oid4vci-1_0-issuer-happy-flow"]}), encoding="utf-8"
    )
    code, document = run_cli(
        tmp_path,
        suite(),
        "--component",
        "certify",
        "--benchmark",
        str(benchmark),
        "--only",
        "*issuer-metadata*",
    )

    assert code == 1
    assert document["benchmarkMet"] is False
    assert "missing required modules" in " ".join(document["benchmarkReasons"])


def test_official_script_mode_cannot_report_a_false_green():
    """Without module level results the gate must not claim success."""
    import argparse

    args = argparse.Namespace(
        accept_official_exit_code=False,
        suite_url="https://example",
    )
    plans = [{"component": "certify", "officialScriptExit": 0, "modules": []}]
    # finish_official writes results.json, so run it in a temp cwd.
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        args.output_dir = Path(tmp)
        previous = os.getcwd()
        os.chdir(tmp)
        try:
            code = run_conformance.finish_official(args, "certify", "now", plans, {})
            document = json.loads((Path(tmp) / "results.json").read_text(encoding="utf-8"))
        finally:
            os.chdir(previous)

    assert code == 1
    assert document["benchmarkMet"] is False
    assert "no module level results" in " ".join(document["benchmarkReasons"])


def test_official_script_mode_can_opt_into_the_exit_code():
    import argparse
    import os
    import tempfile

    args = argparse.Namespace(accept_official_exit_code=True, suite_url="https://example")
    plans = [{"component": "certify", "officialScriptExit": 0, "modules": []}]
    with tempfile.TemporaryDirectory() as tmp:
        args.output_dir = Path(tmp)
        previous = os.getcwd()
        os.chdir(tmp)
        try:
            code = run_conformance.finish_official(args, "certify", "now", plans, {})
        finally:
            os.chdir(previous)
    assert code == 0
