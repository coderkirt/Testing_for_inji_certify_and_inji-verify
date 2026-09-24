"""Diff two harness results.json files and emit a human-readable summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _index(results: dict[str, Any]) -> dict[str, str]:
    indexed: dict[str, str] = {}
    for plan in results.get("plans", []):
        component = plan.get("component", "")
        for module in plan.get("modules", []):
            key = f"{component}::{module.get('testModule')}"
            indexed[key] = (module.get("mapped") or module.get("result") or "").upper()
    return indexed


def diff_results(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev = _index(previous)
    curr = _index(current)
    keys = sorted(set(prev) | set(curr))
    regressions = []
    fixes = []
    added = []
    removed = []
    unchanged = []
    for key in keys:
        if key not in prev:
            added.append(key)
        elif key not in curr:
            removed.append(key)
        elif prev[key] != curr[key]:
            entry = {"module": key, "from": prev[key], "to": curr[key]}
            if curr[key] == "FAIL" and prev[key] == "PASS":
                regressions.append(entry)
            elif curr[key] == "PASS" and prev[key] == "FAIL":
                fixes.append(entry)
            else:
                unchanged.append(entry)
        else:
            unchanged.append({"module": key, "result": curr[key]})
    return {
        "regressions": regressions,
        "fixes": fixes,
        "added": added,
        "removed": removed,
        "changedOther": [item for item in unchanged if "from" in item],
        "summary": {
            "previousModules": len(prev),
            "currentModules": len(curr),
            "regressions": len(regressions),
            "fixes": len(fixes),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff two conformance results.json files")
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = diff_results(
        json.loads(args.previous.read_text(encoding="utf-8")),
        json.loads(args.current.read_text(encoding="utf-8")),
    )
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["summary"]["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
