#!/usr/bin/env python3
"""Programmatic OpenID conformance runner for Inji Certify and Inji Verify.

Wraps the suite REST API (same flow as run-test-plan.py): create plan, start
each module, poll to FINISHED, export, emit results.json for the TestNG bridge.

Official scripts/run-test-plan.py can be used instead with --official-script.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_render import endpoint_mapping, load_json, render_plan_config
from oidf_client import OidfClient
from result_diff import diff_results

CONFIG_DIR = ROOT / "configs"

PASS_RESULTS = {"PASSED", "PASSED_WITH_WARNINGS", "WARNING", "REVIEW"}
FAIL_RESULTS = {"FAILED", "FAILURE", "INTERRUPTED"}
SKIP_RESULTS = {"SKIPPED", "SKIP", "NOT_RUN"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def module_key(name: str, variant: Optional[dict]) -> str:
    if not variant:
        return name
    parts = "".join(f"[{key}={variant[key]}]" for key in sorted(variant))
    return name + parts


def load_expected_failures(path: Path) -> dict[str, str]:
    data = load_json(path)
    modules = data.get("modules", data)
    if isinstance(modules, dict):
        return {str(key): str(value if isinstance(value, str) else value.get("comment", "expected")) for key, value in modules.items()}
    if isinstance(modules, list):
        out: dict[str, str] = {}
        for item in modules:
            if isinstance(item, str):
                out[item] = "expected"
            elif isinstance(item, dict) and item.get("testModule"):
                out[item["testModule"]] = str(item.get("reason", "expected"))
        return out
    return {}


def load_expected_skips(path: Path) -> set[str]:
    data = load_json(path)
    modules = data.get("modules", [])
    return {str(item) for item in modules}


def map_result(raw: str, expected_failure: bool, skipped: bool) -> str:
    if skipped:
        return "SKIP"
    status = (raw or "").upper()
    if expected_failure and status in FAIL_RESULTS:
        return "SKIP"
    if status in PASS_RESULTS or status in {"FINISHED"}:
        return "PASS"
    if status in SKIP_RESULTS:
        return "SKIP"
    if status in FAIL_RESULTS:
        return "FAIL"
    return "FAIL" if status else "SKIP"


def evaluate_benchmark(summary: dict[str, Any], benchmark: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    total = max(summary.get("total", 0), 1)
    pass_rate = summary.get("passed", 0) / total
    min_rate = float(benchmark.get("minPassRate", 1.0))
    if pass_rate + 1e-9 < min_rate:
        reasons.append(f"pass rate {pass_rate:.2%} < minPassRate {min_rate:.2%}")
    if benchmark.get("failOnUnexpectedFailure", True) and summary.get("unexpectedFailures", 0):
        reasons.append(f"{summary['unexpectedFailures']} unexpected failure(s)")
    if benchmark.get("failOnUnexpectedSkip") and summary.get("unexpectedSkips", 0):
        reasons.append(f"{summary['unexpectedSkips']} unexpected skip(s)")
    required = set(benchmark.get("requiredModules") or [])
    missing = required - set(summary.get("ranModules") or [])
    if missing:
        reasons.append(f"missing required modules: {sorted(missing)}")
    return (len(reasons) == 0, reasons)


def run_official_script(
    official: Path,
    plan_name: str,
    config_path: Path,
    export_dir: Path,
    expected_failures: Path,
    expected_skips: Path,
    parallel: bool,
) -> int:
    cmd = [
        sys.executable,
        str(official),
        "--export-dir",
        str(export_dir),
        "--expected-failures-file",
        str(expected_failures),
        "--expected-skips-file",
        str(expected_skips),
    ]
    if not parallel:
        cmd.append("--no-parallel")
    cmd.extend([plan_name, str(config_path)])
    print("Invoking official runner:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(official.parent))


def execute_plan(
    client: OidfClient,
    component: str,
    plan_meta: dict[str, Any],
    mapping: dict[str, str],
    expected_failures: dict[str, str],
    expected_skips: set[str],
    export_dir: Path,
    module_timeout: int,
    parallel_modules: bool,
) -> dict[str, Any]:
    variant = load_json(CONFIG_DIR / plan_meta["variantFile"])
    config = render_plan_config(CONFIG_DIR / plan_meta["configFile"], mapping)
    plan_name = plan_meta["planName"]
    print(f"Creating plan {plan_name} for {component}")
    created = client.create_plan(plan_name, variant, config)
    plan_id = created.get("id") or created.get("planId")
    if not plan_id:
        raise RuntimeError(f"Plan create returned no id: {created}")
    plan = client.get_plan(plan_id)
    modules = plan.get("modules") or []
    print(f"Plan {plan_id} has {len(modules)} module(s)")

    def run_one(module: dict[str, Any]) -> dict[str, Any]:
        name = module.get("testModule") or module.get("testName")
        module_variant = module.get("variant") or variant
        key = module_key(name, module_variant)
        if name in expected_skips or key in expected_skips:
            return {
                "testModule": name,
                "variant": module_variant,
                "testId": None,
                "status": "SKIPPED",
                "result": "SKIPPED",
                "mapped": "SKIP",
                "expectedFailure": False,
                "expectedSkip": True,
                "reason": "listed in expected-skips.json",
            }
        started = client.start_module(plan_id, name, module_variant)
        test_id = started.get("id") or started.get("testId")
        info = client.wait_for_finished(test_id, timeout=module_timeout)
        raw_result = (
            info.get("result")
            or info.get("testResult")
            or info.get("status")
            or ""
        )
        expected = key in expected_failures or name in expected_failures
        mapped = map_result(str(raw_result), expected, False)
        return {
            "testModule": name,
            "variant": module_variant,
            "testId": test_id,
            "status": info.get("status"),
            "result": raw_result,
            "mapped": mapped,
            "expectedFailure": expected,
            "expectedSkip": False,
            "reason": expected_failures.get(key) or expected_failures.get(name),
        }

    results: list[dict[str, Any]] = []
    if parallel_modules and len(modules) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(modules))) as pool:
            futures = {pool.submit(run_one, module): module for module in modules}
            for future in as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: item["testModule"] or "")
    else:
        for module in modules:
            results.append(run_one(module))

    export = client.export_html(plan_id, export_dir / component)
    return {
        "component": component,
        "role": plan_meta.get("role"),
        "planName": plan_name,
        "planId": plan_id,
        "variant": variant,
        "exportHtml": str(export) if export else None,
        "modules": results,
    }


def summarize(plans: list[dict[str, Any]]) -> dict[str, Any]:
    passed = failed = skipped = unexpected = unexpected_skips = 0
    ran: list[str] = []
    for plan in plans:
        for module in plan.get("modules", []):
            ran.append(module["testModule"])
            mapped = module.get("mapped")
            if mapped == "PASS":
                passed += 1
            elif mapped == "SKIP":
                skipped += 1
                if not module.get("expectedSkip") and not module.get("expectedFailure"):
                    unexpected_skips += 1
            else:
                failed += 1
                if not module.get("expectedFailure"):
                    unexpected += 1
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "unexpectedFailures": unexpected,
        "unexpectedSkips": unexpected_skips,
        "total": passed + failed + skipped,
        "ranModules": ran,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenID conformance plans against Inji modules")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--component", choices=["certify", "verify"])
    group.add_argument("--combined", action="store_true")
    parser.add_argument("--suite-url", default=os.environ.get("CONFORMANCE_SERVER", "https://localhost.emobix.co.uk:8443/"))
    parser.add_argument("--token", default=os.environ.get("CONFORMANCE_TOKEN"))
    parser.add_argument("--certify-issuer-url", default=os.environ.get("CERTIFY_ISSUER_URL") or os.environ.get("ENV_ENDPOINT", "http://certify-nginx"))
    parser.add_argument("--verify-endpoint", default=os.environ.get("VERIFY_ENDPOINT", "http://verify-service:8080/v1/verify"))
    parser.add_argument("--credential-configuration-id", default=os.environ.get("CERTIFY_CREDENTIAL_CONFIGURATION_ID", "FarmerCredential"))
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--expected-failures", type=Path, default=CONFIG_DIR / "expected-failures.json")
    parser.add_argument("--expected-skips", type=Path, default=CONFIG_DIR / "expected-skips.json")
    parser.add_argument("--benchmark", type=Path, default=CONFIG_DIR / "benchmark.json")
    parser.add_argument("--diff-against", type=Path)
    parser.add_argument("--official-script", type=Path, help="Optional path to official run-test-plan.py")
    parser.add_argument("--parallel", action="store_true", help="Run certify+verify plans and modules concurrently")
    parser.add_argument("--module-timeout", type=int, default=int(os.environ.get("OIDF_MODULE_TIMEOUT", "600")))
    parser.add_argument("--skip-wait", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    components = ["certify", "verify"] if args.combined else [args.component]
    mode = "combined" if args.combined else args.component
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plans_meta = load_json(CONFIG_DIR / "plans.json")
    mapping = endpoint_mapping(args.certify_issuer_url, args.verify_endpoint, args.credential_configuration_id)
    expected_failures = load_expected_failures(args.expected_failures)
    expected_skips = load_expected_skips(args.expected_skips)
    benchmark = load_json(args.benchmark)

    started = utc_now()
    plans: list[dict[str, Any]] = []

    if args.official_script:
        for component in components:
            meta = plans_meta[component]
            rendered = render_plan_config(CONFIG_DIR / meta["configFile"], mapping)
            rendered_path = args.output_dir / f"{component}-plan.rendered.json"
            rendered_path.write_text(json.dumps(rendered, indent=2), encoding="utf-8")
            code = run_official_script(
                args.official_script,
                meta["planName"],
                rendered_path,
                args.output_dir / component,
                args.expected_failures,
                args.expected_skips,
                args.parallel,
            )
            plans.append(
                {
                    "component": component,
                    "planName": meta["planName"],
                    "officialScriptExit": code,
                    "modules": [],
                }
            )
        document = {
            "runId": f"{mode}-{int(time.time())}",
            "mode": mode,
            "startedAt": started,
            "finishedAt": utc_now(),
            "suiteUrl": args.suite_url,
            "driver": "run-test-plan.py",
            "plans": plans,
            "summary": {"note": "Official script was used; inspect export-dir for detailed results"},
            "benchmarkMet": all(plan.get("officialScriptExit", 1) == 0 for plan in plans),
        }
        (args.output_dir / "results.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return 0 if document["benchmarkMet"] else 1

    with OidfClient(args.suite_url, token=args.token, verify_ssl=False) as client:
        if not args.skip_wait:
            client.wait_until_ready()

        def run_component(component: str) -> dict[str, Any]:
            return execute_plan(
                client,
                component,
                plans_meta[component],
                mapping,
                expected_failures,
                expected_skips,
                args.output_dir,
                args.module_timeout,
                args.parallel,
            )

        if args.parallel and len(components) > 1:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run_component, component) for component in components]
                plans = [future.result() for future in futures]
        else:
            plans = [run_component(component) for component in components]

    summary = summarize(plans)
    met, reasons = evaluate_benchmark(summary, benchmark)
    document: dict[str, Any] = {
        "runId": f"{mode}-{int(time.time())}",
        "mode": mode,
        "startedAt": started,
        "finishedAt": utc_now(),
        "suiteUrl": args.suite_url,
        "endpoints": mapping,
        "driver": "rest-api",
        "plans": plans,
        "summary": summary,
        "benchmarkMet": met,
        "benchmarkReasons": reasons,
    }
    if args.diff_against and args.diff_against.exists():
        document["diff"] = diff_results(load_json(args.diff_against), document)
        (args.output_dir / "diff.json").write_text(json.dumps(document["diff"], indent=2) + "\n", encoding="utf-8")

    results_path = args.output_dir / "results.json"
    results_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "benchmarkMet": met, "reasons": reasons, "results": str(results_path)}, indent=2))
    return 0 if met else 1


if __name__ == "__main__":
    raise SystemExit(main())
