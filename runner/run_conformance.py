#!/usr/bin/env python3
"""Programmatic OpenID conformance runner for Inji Certify and Inji Verify.

Wraps the suite REST API (same flow as scripts/run-test-plan.py): create plan,
create each module, start it when it does not auto-start, poll to a terminal
state, adjudicate the condition log, export, and emit results.json for the
TestNG bridge.

Design notes:

* A module can never abort the run. Every module is wrapped, and a transport
  error, a timeout or a suite 500 becomes a FAIL with an ``error`` string -
  the plan still exports and still produces a report.
* A module parked in WAITING is a wallet handoff, not a hang. It is recorded
  as a documented SKIP (``handoff: true``) instead of burning the full module
  timeout and killing the plan.
* Modules that never auto-start are started explicitly (``--auto-start``),
  which is what the official driver does for oidcc-server-rotate-keys.
* Intra-plan parallelism is disabled when the plan config declares an
  ``alias``, matching run-test-plan.py, because the suite cannot register the
  same alias concurrently.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import benchmark as benchmark_module
import expected as expected_module
from conditions import analyze_logs
from config_render import CONFIG_DIR, endpoint_mapping, load_json, render_plan_config
from oidf_client import (
    ConformanceError,
    ConformanceTimeout,
    OidfClient,
    PlanCreateError,
)
from result_diff import diff_results
from results import (
    SETTLED_ERROR,
    SETTLED_FILTERED,
    SETTLED_HANDOFF,
    SETTLED_INTERRUPTED,
    SETTLED_TIMEOUT,
    SETTLED_UNSTARTED,
    make_module,
    map_result,
    module_key,
    summarize,
)

HANDOFF_REASON = (
    "suite is waiting for a wallet to complete the presentation; "
    "run the handoff documented in docs/handoff.md or list the module in expected-skips.json"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------- arguments


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OpenID conformance plans against Inji modules"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--component", choices=["certify", "verify"])
    group.add_argument("--combined", action="store_true")

    parser.add_argument(
        "--suite-url",
        default=os.environ.get("CONFORMANCE_SERVER", "https://localhost.emobix.co.uk:8443/"),
    )
    parser.add_argument("--token", default=os.environ.get("CONFORMANCE_TOKEN"))
    parser.add_argument(
        "--certify-issuer-url",
        default=os.environ.get("CERTIFY_ISSUER_URL") or os.environ.get("ENV_ENDPOINT", "http://certify-nginx"),
    )
    parser.add_argument(
        "--verify-endpoint",
        default=os.environ.get("VERIFY_ENDPOINT", "http://verify-service:8080/v1/verify"),
    )
    parser.add_argument(
        "--credential-configuration-id",
        default=os.environ.get("CERTIFY_CREDENTIAL_CONFIGURATION_ID", "FarmerCredential"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--expected-failures", type=Path, default=CONFIG_DIR / "expected-failures.json")
    parser.add_argument("--expected-skips", type=Path, default=CONFIG_DIR / "expected-skips.json")
    parser.add_argument("--benchmark", type=Path, default=CONFIG_DIR / "benchmark.json")
    parser.add_argument("--diff-against", type=Path)
    parser.add_argument("--baseline", type=Path, help="benchmark baseline results.json")
    parser.add_argument("--official-script", type=Path, help="optional path to official run-test-plan.py")
    parser.add_argument(
        "--accept-official-exit-code",
        action="store_true",
        help="treat the official script's exit code as the gate; without this an "
        "official-script run cannot report module results and fails the gate",
    )
    parser.add_argument("--parallel", action="store_true", help="run plans/modules concurrently where safe")
    parser.add_argument("--force-parallel-modules", action="store_true", help="parallel modules even with an alias")
    parser.add_argument("--auto-start", action="store_true", default=True)
    parser.add_argument("--no-auto-start", dest="auto_start", action="store_false")
    parser.add_argument("--handoff-grace", type=float, default=float(os.environ.get("OIDF_HANDOFF_GRACE", "0")))
    parser.add_argument("--module-timeout", type=int, default=int(os.environ.get("OIDF_MODULE_TIMEOUT", "600")))
    parser.add_argument("--no-condition-analysis", action="store_true")
    parser.add_argument("--fail-fast", action="store_true", help="stop after the first module error")
    parser.add_argument("--skip-wait", action="store_true")
    parser.add_argument("--validate-plans", action="store_true", help="check plan names against api/plan/available")
    parser.add_argument(
        "--only",
        action="append",
        metavar="PATTERN",
        help="run only modules matching a shell wildcard (repeatable, "
        "comma separated); everything else is reported as a filtered SKIP",
    )
    parser.add_argument(
        "--skip",
        action="append",
        metavar="PATTERN",
        help="never run modules matching a shell wildcard (repeatable, comma separated)",
    )
    parsed = parser.parse_args(argv)
    # Normalise once here so every stage sees the same list.
    parsed.only = split_patterns(parsed.only)
    parsed.skip = split_patterns(parsed.skip)
    return parsed


def split_patterns(values: Optional[list[str]]) -> list[str]:
    """Flatten repeatable ``--only a,b`` style flags into single patterns."""
    patterns: list[str] = []
    for value in values or []:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                patterns.append(part)
    return patterns


def module_selected(
    name: str, key: str, only: list[str], skip: list[str]
) -> tuple[bool, Optional[str]]:
    """Selective execution: decide whether one module should be driven.

    Patterns are matched against both the bare module name and the official
    ``name[dimension=value]`` key, so a caller can select a whole module
    (``--only oid4vci-1_0-issuer-*``) or one variant of it
    (``--only '*[credential_format=mdoc]'``).

    A module that is not selected is still *reported* - as a filtered SKIP -
    rather than dropped, so a selective run never looks like a full green run.
    """
    targets = (name, key)
    if skip and any(fnmatch.fnmatchcase(target, pattern) for pattern in skip for target in targets):
        return False, "excluded by --skip " + ", ".join(skip)
    if only and not any(
        fnmatch.fnmatchcase(target, pattern) for pattern in only for target in targets
    ):
        return False, "not selected by --only " + ", ".join(only)
    return True, None


# ------------------------------------------------------------------ plan helper


def plan_context(meta: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Render a plan's variant + config once, returning everything the run needs."""
    variant = load_json(CONFIG_DIR / meta["variantFile"])
    config_path = CONFIG_DIR / meta["configFile"]
    config = render_plan_config(config_path, mapping)
    return {
        "planName": meta["planName"],
        "component": meta["component"],
        "role": meta.get("role"),
        "configFile": config_path.name,
        "variant": variant,
        "config": config,
        "alias": config.get("alias"),
    }


def validate_plans(client: OidfClient, contexts: list[dict[str, Any]]) -> int:
    """Check plan names and variant keys against the running suite."""
    try:
        available = client.available_plans()
    except ConformanceError as exc:
        print(f"Could not read api/plan/available: {exc}", file=sys.stderr)
        return 1

    known: dict[str, Any] = {}
    if isinstance(available, dict):
        for entry in available.get("plans") or available.get("data") or []:
            if isinstance(entry, dict) and entry.get("planName"):
                known[entry["planName"]] = entry
    elif isinstance(available, list):
        for entry in available:
            if isinstance(entry, dict) and entry.get("planName"):
                known[entry["planName"]] = entry

    problems = 0
    for context in contexts:
        name = context["planName"]
        if name not in known:
            print(f"  [!] plan '{name}' is not offered by this suite build")
            problems += 1
            continue
        supported = set()
        for key in ("variant", "variants"):
            value = known[name].get(key)
            if isinstance(value, dict):
                supported.update(value.keys())
        unknown = sorted(set(context["variant"]) - supported) if supported else []
        print(
            f"  [ok] {name}: {len(supported)} variant dimension(s) offered"
            + (f"; not offered by this build: {unknown}" if unknown else "")
        )
        if unknown:
            problems += 1
    return 1 if problems else 0


# ------------------------------------------------------------------ one module


def run_module(
    client: OidfClient,
    context: dict[str, Any],
    plan_id: str,
    module: dict[str, Any],
    expected_failures: dict[str, str],
    expected_failure_conditions: list[dict],
    expected_skip_modules: set[str],
    expected_skip_conditions: list[dict],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Resolve exactly one module into a reportable record. Never raises."""
    name = module.get("testModule") or module.get("testName") or "unknown"
    variant = module.get("variant") or context["variant"]
    key = module_key(name, variant)
    common = {
        "component": context["component"],
        "plan_name": context["planName"],
        "config_file": context["configFile"],
        "test_module": name,
        "variant": variant,
    }

    # Module level expected skip: documented up front, never started.
    if name in expected_skip_modules or key in expected_skip_modules:
        return make_module(
            **common,
            mapped="SKIP",
            expected_skip=True,
            outcome="EXPECTED_SKIP",
            reason="listed in expected-skips.json",
        )

    try:
        created = client.start_module(plan_id, name, variant)
    except ConformanceError as exc:
        return make_module(
            **common,
            mapped="FAIL",
            outcome=SETTLED_ERROR,
            reason="could not create module instance",
            error=str(exc),
        )

    test_id = created.get("id") or created.get("testId")
    if not test_id:
        return make_module(
            **common,
            mapped="FAIL",
            outcome=SETTLED_ERROR,
            reason="suite did not return a module id",
            error=json.dumps(created)[:300],
        )

    try:
        outcome, info = client.wait_for_settled(
            test_id,
            timeout=args.module_timeout,
            handoff_grace=args.handoff_grace,
            auto_start=args.auto_start,
        )
    except ConformanceError as exc:
        return make_module(
            **common,
            test_id=test_id,
            mapped="FAIL",
            outcome=SETTLED_ERROR,
            reason="error while polling the suite",
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - belt and braces
        return make_module(
            **common,
            test_id=test_id,
            mapped="FAIL",
            outcome=SETTLED_ERROR,
            reason="unexpected error while polling the suite",
            error=f"{type(exc).__name__}: {exc}",
        )

    status = info.get("status")
    result = client.module_result(info)
    expected_module_failure = key in expected_failures or name in expected_failures

    if outcome == SETTLED_HANDOFF:
        return make_module(
            **common,
            test_id=test_id,
            status=status,
            result=result or None,
            mapped="SKIP",
            handoff=True,
            expected_skip=True,
            outcome=SETTLED_HANDOFF,
            reason=HANDOFF_REASON,
        )

    if outcome == SETTLED_UNSTARTED:
        return make_module(
            **common,
            test_id=test_id,
            status=status,
            mapped="SKIP",
            outcome=SETTLED_UNSTARTED,
            reason="module stayed in CONFIGURED and could not be started",
        )

    if outcome == SETTLED_TIMEOUT:
        return make_module(
            **common,
            test_id=test_id,
            status=status,
            result=result or None,
            mapped="FAIL",
            outcome=SETTLED_TIMEOUT,
            reason=f"module did not finish within {args.module_timeout}s",
        )

    # Terminal: adjudicate the condition log.
    analysis: Optional[dict] = None
    if not args.no_condition_analysis:
        try:
            logs = client.get_log(test_id)
            selected_failures = expected_module.select(
                expected_failure_conditions, name, context["configFile"], variant
            )
            selected_skips = expected_module.select(
                expected_skip_conditions, name, context["configFile"], variant
            )
            analysis = analyze_logs(logs, result, selected_failures, selected_skips)
        except Exception as exc:  # noqa: BLE001 - analysis is additive
            print(f"Condition analysis unavailable for {name}: {exc}")

    mapped, reason = map_result(result, expected_module_failure)

    # A condition level expectation must be able to make the module acceptable:
    # if the only failing conditions are ones expected-failures.json covers,
    # the module is a documented skip rather than a regression.
    if (
        mapped == "FAIL"
        and analysis
        and not analysis.get("unexpectedFailures")
        and analysis.get("expectedFailures")
    ):
        mapped = "SKIP"
        expected_module_failure = True
        reason = "all failing conditions are covered by expected-failures.json"

    if outcome == SETTLED_INTERRUPTED:
        mapped = "FAIL" if not expected_module_failure else "SKIP"
        reason = reason or "module was interrupted"

    return make_module(
        **common,
        test_id=test_id,
        status=status,
        result=result or None,
        mapped=mapped,
        expected_failure=expected_module_failure,
        outcome=outcome,
        reason=reason,
        analysis=analysis,
    )


# ------------------------------------------------------------------- one plan


def execute_plan(
    client: OidfClient,
    context: dict[str, Any],
    args: argparse.Namespace,
    mapping: dict[str, str],
    expected_failures: dict[str, str],
    expected_failure_conditions: list[dict],
    expected_skip_modules: set[str],
    expected_skip_conditions: list[dict],
) -> dict[str, Any]:
    print(f"Creating plan {context['planName']} for {context['component']}")
    try:
        created = client.create_plan(context["planName"], context["variant"], context["config"])
    except PlanCreateError as exc:
        return {
            "component": context["component"],
            "role": context["role"],
            "planName": context["planName"],
            "configFile": context["configFile"],
            "planId": None,
            "variant": context["variant"],
            "modules": [],
            "error": str(exc),
        }

    plan_id = created.get("id") or created.get("planId")
    if not plan_id:
        return {
            "component": context["component"],
            "role": context["role"],
            "planName": context["planName"],
            "configFile": context["configFile"],
            "planId": None,
            "variant": context["variant"],
            "modules": [],
            "error": f"plan create returned no id: {json.dumps(created)[:300]}",
        }

    modules = client.plan_modules(created)
    print(f"Plan {plan_id} has {len(modules)} module(s)")

    # Selective execution: keep the plan intact but drive only the modules the
    # caller asked for. Unselected modules are reported as filtered skips.
    selected: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for module in modules:
        name = module.get("testModule") or module.get("testName") or "unknown"
        module_variant = module.get("variant") or context["variant"]
        keep, skip_reason = module_selected(
            name, module_key(name, module_variant), args.only, args.skip
        )
        if keep:
            selected.append(module)
            continue
        filtered.append(
            make_module(
                component=context["component"],
                plan_name=context["planName"],
                config_file=context["configFile"],
                test_module=name,
                variant=module_variant,
                mapped="SKIP",
                filtered=True,
                outcome=SETTLED_FILTERED,
                reason=skip_reason,
            )
        )
    if filtered:
        print(
            f"Selection filter leaves {len(selected)} of {len(modules)} module(s) in {context['planName']}"
        )

    # The suite cannot register one alias concurrently, so intra-plan
    # parallelism is off whenever the config declares an alias.
    parallel_modules = bool(args.parallel) and len(selected) > 1
    if parallel_modules and context["alias"] and not args.force_parallel_modules:
        print(
            f"Config declares alias '{context['alias']}' - running modules serially "
            "as run-test-plan.py does (override with --force-parallel-modules)"
        )
        parallel_modules = False

    results: list[dict[str, Any]] = []
    if parallel_modules:
        with ThreadPoolExecutor(max_workers=min(4, len(selected))) as pool:
            futures = {
                pool.submit(
                    run_module,
                    client,
                    context,
                    plan_id,
                    module,
                    expected_failures,
                    expected_failure_conditions,
                    expected_skip_modules,
                    expected_skip_conditions,
                    args,
                ): module
                for module in selected
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    module = futures[future]
                    results.append(
                        make_module(
                            component=context["component"],
                            plan_name=context["planName"],
                            config_file=context["configFile"],
                            test_module=module.get("testModule") or "unknown",
                            variant=module.get("variant") or context["variant"],
                            mapped="FAIL",
                            outcome=SETTLED_ERROR,
                            reason="module worker crashed",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
        results.sort(key=lambda item: item.get("testModule") or "")
    else:
        for module in selected:
            result = run_module(
                client,
                context,
                plan_id,
                module,
                expected_failures,
                expected_failure_conditions,
                expected_skip_modules,
                expected_skip_conditions,
                args,
            )
            results.append(result)
            marker = {"PASS": "ok  ", "FAIL": "FAIL", "SKIP": "skip"}.get(result["mapped"], "?   ")
            print(f"  [{marker}] {result['testModule']} -> {result['mapped']} ({result.get('outcome')})")
            if args.fail_fast and result["mapped"] == "FAIL":
                print("--fail-fast: stopping this plan after the first failure")
                break

    for result in filtered:
        print(f"  [skip] {result['testModule']} -> SKIP ({result.get('outcome')})")
    results.extend(filtered)
    results.sort(key=lambda item: item.get("testModule") or "")

    export_dir = args.output_dir / context["component"]
    html = client.export_html(plan_id, export_dir)
    exported = client.export_json(plan_id, export_dir)

    return {
        "component": context["component"],
        "role": context["role"],
        "planName": context["planName"],
        "configFile": context["configFile"],
        "planId": plan_id,
        "variant": context["variant"],
        "alias": context["alias"],
        "exportHtml": str(html) if html else None,
        "exportJson": str(exported) if exported else None,
        "modules": results,
    }


# ------------------------------------------------------------- official script


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


# -------------------------------------------------------------------- main


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    components = ["certify", "verify"] if args.combined else [args.component]
    mode = "combined" if args.combined else args.component
    args.output_dir.mkdir(parents=True, exist_ok=True)

    plans_meta = load_json(CONFIG_DIR / "plans.json")
    mapping = endpoint_mapping(
        args.certify_issuer_url, args.verify_endpoint, args.credential_configuration_id
    )
    expected_failures, expected_failure_conditions = expected_module.load_expected_failures(
        args.expected_failures
    )
    expected_skip_modules, expected_skip_conditions = expected_module.load_expected_skips(
        args.expected_skips
    )
    benchmark_config = load_json(args.benchmark) if args.benchmark.exists() else {}

    started = utc_now()
    contexts = [plan_context(plans_meta[component], mapping) for component in components]

    with OidfClient(args.suite_url, token=args.token, verify_ssl=False) as client:
        if not args.skip_wait:
            client.wait_until_ready()

        if args.validate_plans:
            return validate_plans(client, contexts)

        if args.official_script:
            plans: list[dict[str, Any]] = []
            for context in contexts:
                rendered_path = args.output_dir / f"{context['component']}-plan.rendered.json"
                rendered_path.write_text(
                    json.dumps(context["config"], indent=2) + "\n", encoding="utf-8"
                )
                code = run_official_script(
                    args.official_script,
                    context["planName"],
                    rendered_path,
                    args.output_dir / context["component"],
                    args.expected_failures,
                    args.expected_skips,
                    args.parallel,
                )
                plans.append(
                    {
                        "component": context["component"],
                        "role": context["role"],
                        "planName": context["planName"],
                        "configFile": context["configFile"],
                        "officialScriptExit": code,
                        "modules": [],
                    }
                )
            return finish_official(args, mode, started, plans, benchmark_config)

        def run_component(context: dict[str, Any]) -> dict[str, Any]:
            return execute_plan(
                client,
                context,
                args,
                mapping,
                expected_failures,
                expected_failure_conditions,
                expected_skip_modules,
                expected_skip_conditions,
            )

        if args.parallel and len(contexts) > 1:
            with ThreadPoolExecutor(max_workers=len(contexts)) as pool:
                plans = [future.result() for future in as_completed(
                    [pool.submit(run_component, context) for context in contexts]
                )]
            plans.sort(key=lambda plan: plan.get("component") or "")
        else:
            plans = [run_component(context) for context in contexts]

    return finish_rest(args, mode, started, plans, mapping, benchmark_config)


def finish_official(
    args: argparse.Namespace,
    mode: str,
    started: str,
    plans: list[dict[str, Any]],
    benchmark_config: dict[str, Any],
) -> int:
    """Write results for an official-script run.

    The official script owns its own pass/fail logic and does not give us a
    module list, so the TestNG bridge would see zero modules and report
    everything as skipped. That is a false green, so by default the gate fails
    unless the caller explicitly accepts the script's exit code.
    """
    exit_ok = all(plan.get("officialScriptExit", 1) == 0 for plan in plans)
    if args.accept_official_exit_code:
        met, reasons = exit_ok, [] if exit_ok else ["official script exited non-zero"]
    else:
        met = False
        reasons = [
            "official script mode produces no module level results; "
            "pass --accept-official-exit-code to gate on the script exit code, "
            "or drop --official-script to use the REST driver"
        ]

    document = {
        "runId": f"{mode}-{int(time.time())}",
        "mode": mode,
        "driver": "run-test-plan.py",
        "startedAt": started,
        "finishedAt": utc_now(),
        "suiteUrl": args.suite_url,
        "plans": plans,
        "summary": {"note": "official script used; module level results are in the export zip"},
        "benchmarkMet": met,
        "benchmarkReasons": reasons,
    }
    results_path = args.output_dir / "results.json"
    results_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"benchmarkMet": met, "reasons": reasons, "results": str(results_path)}, indent=2))
    return 0 if met else 1


def finish_rest(
    args: argparse.Namespace,
    mode: str,
    started: str,
    plans: list[dict[str, Any]],
    mapping: dict[str, str],
    benchmark_config: dict[str, Any],
) -> int:
    summary = summarize(plans)

    baseline_path = args.baseline
    if baseline_path is None and benchmark_config.get("baselineFile"):
        candidate = CONFIG_DIR / str(benchmark_config["baselineFile"])
        baseline_path = candidate if candidate.exists() else None

    diff: Optional[dict[str, Any]] = None
    diff_source = args.diff_against or baseline_path
    if diff_source and Path(diff_source).exists():
        try:
            diff = diff_results(load_json(Path(diff_source)), {"plans": plans})
        except Exception as exc:  # noqa: BLE001 - diff is advisory
            print(f"Could not diff against {diff_source}: {exc}", file=sys.stderr)

    gate = benchmark_module.evaluate(summary, benchmark_config, diff)

    document: dict[str, Any] = {
        "runId": f"{mode}-{int(time.time())}",
        "mode": mode,
        "driver": "rest-api",
        "startedAt": started,
        "finishedAt": utc_now(),
        "suiteUrl": args.suite_url,
        "endpoints": mapping,
        "plans": plans,
        "summary": summary,
        "benchmarkMet": gate["met"],
        "benchmarkReasons": gate["reasons"],
        "benchmarkMetrics": gate["metrics"],
        "benchmarkChecks": gate["checks"],
    }
    if args.only or args.skip:
        # Record the filter in the artifact itself: a selective run must be
        # distinguishable later from a full run that simply skipped things.
        document["selection"] = {"only": args.only, "skip": args.skip}
    if diff is not None:
        document["diff"] = diff
        document["diffAgainst"] = str(diff_source)

    results_path = args.output_dir / "results.json"
    results_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(benchmark_module.describe(gate))
    print(json.dumps({"summary": summary, "results": str(results_path)}, indent=2))
    return 0 if gate["met"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception:  # noqa: BLE001 - always show where it broke
        traceback.print_exc()
        raise SystemExit(1)
