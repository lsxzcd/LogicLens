from __future__ import annotations

import json
import re
from pathlib import Path

# Stage sections as written into the combined log by the flow runner, e.g.
# "===== synthesis.log =====".
_STAGE_HEADER = re.compile(r"^=====\s*(?P<name>[a-z]+)\.log\s*=====\s*$", re.M)


def load_patterns(path: Path) -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def stage_log(log_text: str, stage: str) -> str:
    """Return the section of a combined log belonging to one stage.

    The runner concatenates every stage's output, so a pattern such as
    "mismatch" can match text an unrelated stage produced. A sandbox-induced
    synthesis failure was being classified as a simulation mismatch for exactly
    that reason, which then sent the repair loop after the wrong problem: the
    simulation had actually passed with zero mismatches. When no headers are
    present the whole text is returned, so a bare per-stage log still works.
    """
    matches = list(_STAGE_HEADER.finditer(log_text))
    if not matches:
        return log_text
    for index, match in enumerate(matches):
        if match.group("name") != stage:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(log_text)
        return log_text[match.end() : end]
    return ""


def classify_error(log_text: str, patterns: dict[str, list[str]], stage: str | None = None) -> str:
    """Classify a failure, optionally restricted to the stage that failed.

    `stage` is one of compile / elaboration / simulation / synthesis.
    """
    considered = log_text
    if stage:
        section = stage_log(log_text, stage)
        # If the stage produced no output of its own, fall back to the whole log
        # rather than reporting "unknown" for an obvious failure.
        considered = section if section.strip() else log_text
    lowered = considered.lower()
    for error_type, needles in patterns.items():
        if any(needle.lower() in lowered for needle in needles):
            return error_type
    return "unknown"


def failed_stage(flow: dict) -> str | None:
    """Which stage to attribute a failure to, given the progressive verdict."""
    if not flow.get("compile_pass"):
        return "compile"
    if not flow.get("elaborate_pass"):
        return "elaboration"
    if not flow.get("simulation_pass"):
        return "simulation"
    if not flow.get("synthesis_pass"):
        return "synthesis"
    return None
