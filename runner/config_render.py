"""Render plan JSON templates by substituting ${ENV} and known endpoint keys."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_PLACEHOLDER = re.compile(r"\$\{([A-Z0-9_]+)}")

# Directory holding plans.json, the plan configs and the variant files.
CONFIG_DIR = Path(__file__).resolve().parent / "configs"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def render_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            return mapping.get(key, os.environ.get(key, match.group(0)))

        return _PLACEHOLDER.sub(repl, value)
    if isinstance(value, list):
        return [render_value(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, mapping) for key, item in value.items()}
    return value


def endpoint_mapping(
    certify_issuer_url: str,
    verify_endpoint: str,
    credential_configuration_id: str,
) -> dict[str, str]:
    return {
        "CERTIFY_ISSUER_URL": certify_issuer_url.rstrip("/"),
        "VERIFY_ENDPOINT": verify_endpoint.rstrip("/"),
        "CERTIFY_CREDENTIAL_CONFIGURATION_ID": credential_configuration_id,
        "ENV_ENDPOINT": certify_issuer_url.rstrip("/"),
    }


def render_plan_config(path: Path, mapping: dict[str, str]) -> dict:
    return render_value(load_json(path), mapping)
