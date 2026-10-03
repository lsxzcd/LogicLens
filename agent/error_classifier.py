from __future__ import annotations

import json
from pathlib import Path


def load_patterns(path: Path) -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_error(log_text: str, patterns: dict[str, list[str]]) -> str:
    lowered = log_text.lower()
    for error_type, needles in patterns.items():
        if any(needle.lower() in lowered for needle in needles):
            return error_type
    return "unknown"

