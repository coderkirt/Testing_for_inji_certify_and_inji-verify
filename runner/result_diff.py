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


# Bigger is better. A PASS that becomes a SKIP loses coverage and is treated
# as a regression in its own right, not as an unrelated change.
_RANK = {"PASS": 2, "SKIP": 1, "FAIL": 0}


def diff_results(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev = _index(previous)
    curr = _index(current)
    keys = sorted(set(prev) | set(curr))
    regressions: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []
    added: list[str] = []
    removed: list[str] = []
    changed_other: list[dict[str, Any]] = []
    skipped_now: list[str] = []

    for key in keys:
        if key not in prev:
            added.append(key)
        elif key not in curr:
            removed.append(key)
        else:
            before, after = prev[key], curr[key]
            if after == "SKIP":
                # Surfaced explicitly: a module that became a skip is where an
                # expected-failures entry can quietly hide a real failure.
                skipped_now.append(key)
            if before == after:
                continue
            entry = {"module": key, "from": before, "to": after}
            if _RANK.get(after, 0) < _RANK.get(before, 0):
                regressions.append(entry)
            elif _RANK.get(after, 0) > _RANK.get(before, 0):
                fixes.append(entry)
            else:
                changed_other.append(entry)

    return {
        "regressions": regressions,
        "fixes": fixes,
        "added": added,
        "removed": removed,
        "skippedNow": skipped_now,
        "changedOther": changed_other,
        "summary": {
            "previousModules": len(prev),
            "currentModules": len(curr),
            "regressions": len(regressions),
            "fixes": len(fixes),
            "newlySkipped": len(skipped_now),
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
