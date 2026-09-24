"""Expected failures and expected skips.

Supports the OpenID Foundation ``expected-failures.json`` schema used by
scripts/run-test-plan.py so the same file can be handed to either driver:

    {
      "conditions": [
        {
          "test-name": "oid4vci-1_0-issuer-*",
          "configuration-filename": "issuer-plan.json",
          "variant": "*",
          "current-block": "Credential endpoint",
          "condition": "ValidateCredentialResponse",
          "expected-result": "failure",
          "comment": "why this is tolerated"
        }
      ],
      "modules": {
        "oid4vci-1_0-issuer-some-module": "whole module is known to fail"
      }
    }

* ``test-name`` and ``configuration-filename`` accept shell-style wildcards.
* ``variant`` may be ``"*"`` or a partial mapping - only the listed keys are
  compared, so an entry applies to every unlisted variant.
* ``current-block`` may be ``"*"`` to match any block.
* ``expected-result`` is ``failure`` or ``warning``.

``modules`` is the harness-friendly shorthand: a module name mapped to a
comment (or listed bare in ``expected-skips.json``) is turned into a SKIP at
module granularity without being started.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any, Iterable

# Accepted aliases so a hand-written file does not need kebab-case.
_FIELD_ALIASES = {
    "test-name": ("test-name", "test_name", "testModule", "test-module"),
    "configuration-filename": (
        "configuration-filename",
        "configuration_filename",
        "config-file",
        "configFile",
    ),
    "current-block": ("current-block", "current_block", "block"),
    "condition": ("condition", "src"),
    "expected-result": ("expected-result", "expected_result", "expected"),
    "variant": ("variant",),
    "comment": ("comment", "reason"),
}


def _pick(entry: dict, canonical: str, default: Any = None) -> Any:
    for key in _FIELD_ALIASES[canonical]:
        if key in entry:
            return entry[key]
    return default


def normalize_condition_entry(entry: dict) -> dict:
    """Normalise one entry to the canonical OIDF shape."""
    return {
        "test-name": _pick(entry, "test-name", "*"),
        "configuration-filename": _pick(entry, "configuration-filename", "*"),
        "variant": _pick(entry, "variant", "*"),
        "current-block": _pick(entry, "current-block", "*"),
        "condition": _pick(entry, "condition", "*"),
        "expected-result": str(_pick(entry, "expected-result", "failure") or "failure").lower(),
        "comment": _pick(entry, "comment", ""),
        "__used": False,
    }


def _load_document(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_conditions(path: Path) -> list[dict]:
    """Load condition-level expectations. Missing/!shape file => empty list."""
    document = _load_document(path)
    if document is None:
        return []
    entries: Iterable[Any]
    if isinstance(document, list):
        entries = document
    elif isinstance(document, dict):
        entries = document.get("conditions") or []
    else:
        return []
    return [normalize_condition_entry(item) for item in entries if isinstance(item, dict)]


def load_expected_failures(path: Path) -> tuple[dict[str, str], list[dict]]:
    """Return ``(module_map, conditions)`` for expected failures."""
    document = _load_document(path)
    if document is None:
        return {}, []
    if isinstance(document, list):
        return {}, [normalize_condition_entry(item) for item in document if isinstance(item, dict)]
    if not isinstance(document, dict):
        return {}, {}

    modules = document.get("modules")
    module_map: dict[str, str] = {}
    if isinstance(modules, dict):
        for key, value in modules.items():
            if isinstance(value, str):
                module_map[str(key)] = value
            elif isinstance(value, dict):
                module_map[str(key)] = str(value.get("comment") or value.get("reason") or "expected")
            else:
                module_map[str(key)] = "expected"
    elif isinstance(modules, list):
        for item in modules:
            if isinstance(item, str):
                module_map[item] = "expected"
            elif isinstance(item, dict) and item.get("testModule"):
                module_map[str(item["testModule"])] = str(item.get("reason") or "expected")

    return module_map, [
        normalize_condition_entry(item)
        for item in document.get("conditions") or []
        if isinstance(item, dict)
    ]


def load_expected_skips(path: Path) -> tuple[set[str], list[dict]]:
    """Return ``(module_names, conditions)`` for expected skips."""
    document = _load_document(path)
    if document is None:
        return set(), []
    if isinstance(document, list):
        return set(), [normalize_condition_entry(item) for item in document if isinstance(item, dict)]
    if not isinstance(document, dict):
        return set(), set()

    modules = document.get("modules") or []
    names: set[str] = set()
    if isinstance(modules, str):
        names.add(modules)
    else:
        for item in modules:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict):
                name = item.get("testModule") or item.get("test-name")
                if name:
                    names.add(str(name))

    return names, [
        normalize_condition_entry(item)
        for item in document.get("conditions") or []
        if isinstance(item, dict)
    ]


def matches(
    entry: dict,
    test_name: str,
    configuration_filename: str,
    variant: dict | None,
) -> bool:
    """Loose match on test name, config filename and a partial variant map."""
    if not fnmatch.fnmatch(test_name, entry.get("test-name") or "*"):
        return False
    if not fnmatch.fnmatch(configuration_filename, entry.get("configuration-filename") or "*"):
        return False

    expected_variant = entry.get("variant", "*")
    if expected_variant in ("*", None):
        return True
    if not isinstance(expected_variant, dict):
        return False

    actual = variant or {}
    for key, value in expected_variant.items():
        if key not in actual:
            return False
        if actual[key] != value:
            return False
    return True


def select(
    entries: list[dict],
    test_name: str,
    configuration_filename: str,
    variant: dict | None,
) -> list[dict]:
    """Entries relevant to one module, resetting their ``__used`` marker."""
    chosen = []
    for entry in entries:
        if matches(entry, test_name, configuration_filename, variant):
            entry["__used"] = False
            chosen.append(entry)
    return chosen
