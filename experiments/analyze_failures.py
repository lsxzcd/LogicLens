"""Distil failure patterns from the local evaluation runs.

The skill package is supposed to be built from real failures, so this turns the
per-task run directories into a pattern count rather than an anecdote. It reads
what the agent already wrote and reports:

* the stage each attempt failed at, and the classified error type;
* which structural lint rules fired, including on attempts that the tools
  nevertheless accepted (a heuristic that fires on a passing design is a false
  positive and worth seeing);
* the first line of each stage log, so a pattern can be traced back to evidence.

    py -3 experiments/analyze_failures.py [--runs experiments/runs/eval]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_attempts(runs_dir: Path) -> list[dict]:
    attempts = []
    for result_path in sorted(runs_dir.glob("*__s*/result.json")):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task = result_path.parent.name
        for record in result.get("history") or []:
            attempts.append(
                {
                    "task": task,
                    "attempt": record.get("attempt"),
                    "stage": record.get("failed_stage") or "(passed)",
                    "error_type": record.get("error_type"),
                    "lint": record.get("lint_findings") or [],
                    "sim_pass": record.get("simulation_pass"),
                    "synth_attempted": record.get("synthesis_attempted"),
                    "compile_pass": record.get("compile_pass"),
                    "code_path": result_path.parent / f"attempt_{record.get('attempt')}" / "TopModule.v",
                }
            )
    return attempts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default=str(ROOT / "experiments" / "runs" / "eval"))
    args = parser.parse_args()

    runs_dir = Path(args.runs)
    if not runs_dir.is_dir():
        print(f"no run directory at {runs_dir}")
        return 2

    attempts = load_attempts(runs_dir)
    if not attempts:
        print(f"no result.json found under {runs_dir}")
        return 2

    tasks = sorted({a["task"] for a in attempts})
    print(f"tasks: {len(tasks)}   attempts: {len(attempts)}")
    print()

    print("=== failed stage per attempt ===")
    for stage, count in Counter(a["stage"] for a in attempts).most_common():
        print(f"  {stage:<24} {count}")

    print("\n=== error type per attempt ===")
    for kind, count in Counter(str(a["error_type"]) for a in attempts).most_common():
        print(f"  {kind:<24} {count}")

    rules = Counter()
    for attempt in attempts:
        for finding in attempt["lint"]:
            # Findings render as "[rule] message"; keep the rule name only.
            rules[finding.split("]", 1)[0].lstrip("[")] += 1
    print("\n=== structural lint findings ===")
    if not rules:
        print("  (none)")
    for rule, count in rules.most_common():
        print(f"  {rule:<32} {count}")

    # A rule firing on an attempt that the tools accepted would be a false
    # positive: worth seeing, because the linter must not push correct code
    # away from correct.
    false_positives = [
        a for a in attempts if a["lint"] and a["sim_pass"] and a["synth_attempted"]
    ]
    print(f"\n=== lint fired on an attempt the tools accepted: {len(false_positives)} ===")
    for attempt in false_positives[:5]:
        print(f"  {attempt['task']} attempt {attempt['attempt']}: {attempt['lint']}")

    print("\n=== per task summary ===")
    for task in tasks:
        rows = [a for a in attempts if a["task"] == task]
        final = rows[-1]
        passed = final["sim_pass"] and final["synth_attempted"] and final["compile_pass"]
        print(
            f"  {task[:42]:<44} attempts={len(rows)} final_stage={final['stage']:<16} "
            f"type={str(final['error_type'])[:22]:<24} passed={bool(passed)}"
        )

    print("\n=== last attempt code, where it did not pass ===")
    for task in tasks:
        rows = [a for a in attempts if a["task"] == task]
        final = rows[-1]
        if final["sim_pass"] and final["compile_pass"]:
            continue
        print(f"\n--- {task} (stage={final['stage']}) ---")
        path = final["code_path"]
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines()[:16]:
                print(f"    {line}")
        else:
            print(f"    (no code at {path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
