"""Validate a dataset directory against the layout the flow expects.

A dataset is a directory of task prompts:

    <dataset>/
        counter.txt          <- the natural-language task
        counter.tb.v         <- optional sidecar testbench
        counter.answer.v     <- optional reference implementation (for --mock)

`eval.py` discovers `<task>.txt` / `<task>.md` and `agent.testbench` picks up
the sidecars beside each prompt. This tool reports what is present, what is
missing, and - importantly - which tasks would fall back to a generated
testbench that only performs a smoke check.

Run: py -3 tools/check_dataset.py <dataset-dir>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.task_parser import parse_task  # noqa: E402
from agent.testbench import (  # noqa: E402
    find_sidecar_testbench,
    resolve_reference_answer,
    resolve_testbench,
)

PROMPT_SUFFIXES = (".txt", ".md")


def task_stems(dataset: Path) -> list[str]:
    stems: set[str] = set()
    for suffix in PROMPT_SUFFIXES:
        for path in dataset.rglob(f"*{suffix}"):
            stems.add(str(path.relative_to(dataset).with_suffix("")).replace("\\", "/"))
    return sorted(stems)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a dataset directory")
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--require-testbench",
        action="store_true",
        help="Treat a missing sidecar testbench as an error instead of a warning",
    )
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    if not dataset.is_dir():
        print(f"error: not a directory: {dataset}")
        return 2

    stems = task_stems(dataset)
    if not stems:
        print(f"error: no {'/'.join(PROMPT_SUFFIXES)} prompts found under {dataset}")
        return 2

    no_sidecar: list[str] = []
    no_reference: list[str] = []
    no_ports: list[str] = []
    smoke_only: list[str] = []
    errors: list[str] = []

    for stem in stems:
        prompt = None
        for suffix in PROMPT_SUFFIXES:
            candidate = dataset / f"{stem}{suffix}"
            if candidate.is_file():
                prompt = candidate
                break
        if prompt is None:
            errors.append(f"{stem}: prompt disappeared during the scan")
            continue

        text = prompt.read_text(encoding="utf-8")
        contract = parse_task(text)

        if find_sidecar_testbench(prompt) is None:
            no_sidecar.append(stem)
        if resolve_reference_answer(prompt) is None:
            no_reference.append(stem)
        if not contract.ports:
            no_ports.append(stem)

        reference = resolve_reference_answer(prompt)
        # The real flow resolves the testbench against generated RTL, which is
        # what lets behaviour detection recognise a counter. Use the reference
        # implementation here so this check matches that behaviour instead of
        # reporting a false "smoke only" for every task.
        rtl_text = reference.read_text(encoding="utf-8") if reference else ""
        spec = resolve_testbench(ROOT, prompt, contract, rtl_text=rtl_text, mode="auto")
        # A generated testbench is only trustworthy for the behaviours that
        # actually assert something. "counter" does (verified: it rejects a
        # module that ignores enable and accepts a correct one); anything else
        # falls back to a clock-only smoke check that proves nothing.
        if spec.source == "generated" and spec.behavior not in ("counter",):
            smoke_only.append(stem)

    total = len(stems)
    with_tb = total - len(no_sidecar)
    generated_counter = [stem for stem in no_sidecar if stem not in smoke_only]

    print(f"dataset        : {dataset}")
    print(f"tasks          : {total}")
    print(f"with testbench : {with_tb}  (sidecar)")
    print(f"port list found: {total - len(no_ports)}")
    print(f"generated self-check : {len(generated_counter)}  (real assertions, but generated)")
    print(f"smoke-only     : {len(smoke_only)}")
    print()

    def report(title: str, items: list[str], note: str) -> None:
        if not items:
            return
        print(f"{title} ({len(items)})")
        print(f"  {note}")
        for item in items[:15]:
            print(f"    - {item}")
        if len(items) > 15:
            print(f"    ... and {len(items) - 15} more")
        print()

    report(
        "NOTE: no sidecar testbench",
        no_sidecar,
        "these tasks fall back to a generated testbench instead of the dataset's own check",
    )
    report(
        "NOTE: generated counter self-check in use",
        generated_counter,
        "the generated testbench does assert behaviour (reset clears, increments, holds when "
        "enable is low), so it is a real check - but it is NOT the dataset's reference testbench, "
        "so these results are not directly comparable to the official harness",
    )
    report(
        "WARNING: cannot grade behaviour",
        smoke_only,
        "the generated testbench only drives the clock and asserts nothing, so a pass here does "
        "NOT prove functional correctness",
    )
    report("WARNING: no port list derived", no_ports, "the contract has no ports; check the prompt text")
    report("WARNING: no reference implementation", no_reference, "these tasks cannot be run with --mock")
    report("ERROR", errors, "these need investigation")

    if args.require_testbench and no_sidecar:
        print(f"FAILED: {len(no_sidecar)} task(s) lack a sidecar testbench and --require-testbench was given")
        return 1

    if errors:
        return 1

    if smoke_only:
        print(
            f"Result: layout is valid, but functional correctness is NOT verified for "
            f"{len(smoke_only)} task(s). Add sidecar testbenches before trusting pass rates."
        )
        return 1 if args.require_testbench else 0

    if no_sidecar:
        print(
            f"Result: layout is valid. {len(no_sidecar)} task(s) use a generated self-check rather "
            "than the dataset's own testbench - fine for development, not for reported numbers."
        )
        return 0

    print("Result: layout is valid and every task has a real testbench.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
