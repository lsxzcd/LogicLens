"""Check that the specification parser recovers the interface from each prompt.

The parser only ever sees the natural-language prompt, but for VerilogEval the
ground truth is available: the sibling `<stem>_ref.sv` is the official
implementation of the same task, so its ANSI port list is exactly what the
prompt was describing. Comparing the two turns "does the parser look right?"
into a mechanical check over every task.

Reports, per task:

* whether the top module name was found;
* ports present in the reference but missed by the parser;
* ports the parser produced that the reference does not have (invented ports);
* direction or width disagreements;
* the reset polarity the parser inferred, when the reference has a reset.

Run: py -3 tools/check_parsing.py [dataset-dir]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.task_parser import parse_task, ports_from_rtl  # noqa: E402

DEFAULT_DATASET = ROOT / "experiments" / "data" / "verilogeval"

# Prompts whose own text disagrees with the reference implementation. These are
# upstream inconsistencies, not parser defects: the parser correctly reports
# what the prompt says, and inventing the reference's answer would be guessing.
# Each entry records the disagreement so a future reader does not re-investigate.
KNOWN_UPSTREAM_PROMPT_ISSUES = {
    "Prob031_dff": "prompt lists `- input q`; the reference declares `output q`",
    "Prob062_bugs_mux2": "prompt's snippet shows `output out` (1 bit); the reference is `[7:0]`",
}


@dataclass
class TaskReport:
    stem: str
    top_module: str = ""
    expected_top: str = ""
    missing: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    direction_mismatch: list[str] = field(default_factory=list)
    width_mismatch: list[str] = field(default_factory=list)
    reset_polarity: str = ""
    reset_has_n_suffix: bool = False
    reference_ports: int = 0
    top_module_is_default: bool = False

    @property
    def top_ok(self) -> bool:
        return self.top_module == self.expected_top

    @property
    def clean(self) -> bool:
        return (
            self.top_ok
            and not self.missing
            and not self.invented
            and not self.direction_mismatch
            and not self.width_mismatch
        )


def reference_top_module(reference_text: str) -> str:
    import re

    match = re.search(r"\bmodule\s+(RefModule)\b", reference_text)
    return match.group(1) if match else ""


def analyse(stem: str, prompt: Path, reference: Path) -> TaskReport:
    report = TaskReport(stem=stem)
    contract = parse_task(prompt.read_text(encoding="utf-8"))
    reference_text = reference.read_text(encoding="utf-8")
    truth = ports_from_rtl(reference_text)

    # VerilogEval always asks for `TopModule`; that is the name the testbench
    # instantiates, so it is the expected answer for this suite.
    report.expected_top = "TopModule"
    report.top_module = contract.top_module
    report.top_module_is_default = contract.top_module_is_default
    report.reference_ports = len(truth)

    by_name = {p.name: p for p in contract.ports}
    truth_by_name = {p.name: p for p in truth}

    report.missing = [p.name for p in truth if p.name not in by_name]
    report.invented = [p.name for p in contract.ports if p.name not in truth_by_name]
    for name, expected in truth_by_name.items():
        got = by_name.get(name)
        if got is None:
            continue
        if got.direction != expected.direction:
            report.direction_mismatch.append(f"{name}:{got.direction}!={expected.direction}")
        if got.width != expected.width:
            report.width_mismatch.append(f"{name}:{got.width}!={expected.width}")

    reset = by_name.get(contract.reset_spec.name) or truth_by_name.get(contract.reset_spec.name)
    if reset is not None:
        report.reset_polarity = contract.reset_spec.polarity
        report.reset_has_n_suffix = contract.reset_spec.name.endswith("_n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", nargs="?", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--verbose", action="store_true", help="List every task, not just problems")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    examples = args.dataset / "examples"
    if not examples.is_dir():
        print(f"no examples directory under {args.dataset}")
        return 2

    prompts = sorted(examples.glob("*_prompt.txt"))
    if args.limit:
        prompts = prompts[: args.limit]
    if not prompts:
        print(f"no prompts found under {examples}")
        return 2

    reports: list[TaskReport] = []
    for prompt in prompts:
        stem = prompt.stem[: -len("_prompt")]
        reference = prompt.with_name(f"{stem}_ref.sv")
        if not reference.is_file():
            continue
        reports.append(analyse(stem, prompt, reference))

    clean = [r for r in reports if r.clean]
    # A task whose prompt never names a module cannot be wrong about the name.
    top_problems = [r for r in reports if not r.top_ok and not r.top_module_is_default]
    unnamed = [r for r in reports if not r.top_ok and r.top_module_is_default]
    missing_problems = [r for r in reports if r.missing]
    invented_problems = [r for r in reports if r.invented]
    mismatch_problems = [r for r in reports if r.direction_mismatch or r.width_mismatch]
    upstream = [r for r in reports if r.stem in KNOWN_UPSTREAM_PROMPT_ISSUES]
    unaccounted = [
        r for r in reports
        if not r.clean and r not in upstream and r not in unnamed
    ]

    print(f"dataset      : {args.dataset}")
    print(f"tasks        : {len(reports)}")
    print(f"fully correct: {len(clean)}")
    print(f"known upstream prompt issues: {len(upstream)}")
    print(f"prompt names no module       : {len(unnamed)}")
    print(f"unexplained discrepancies    : {len(unaccounted)}")
    print()

    def show(title: str, items: list[TaskReport], detail) -> None:
        if not items:
            return
        print(f"{title} ({len(items)})")
        for report in items[:20]:
            print(f"  - {report.stem}: {detail(report)}")
        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more")
        print()

    show("top module name wrong", top_problems, lambda r: f"got {r.top_module!r}, expected {r.expected_top!r}")
    show("ports missed", missing_problems, lambda r: f"missing {r.missing}")
    show("ports invented", invented_problems, lambda r: f"invented {r.invented}")
    show(
        "direction/width disagreements",
        mismatch_problems,
        lambda r: " ".join(r.direction_mismatch + r.width_mismatch),
    )
    show(
        "known upstream prompt issues (not parser defects)",
        upstream,
        lambda r: KNOWN_UPSTREAM_PROMPT_ISSUES[r.stem],
    )
    show(
        "prompt does not name a module (placeholder used)",
        unnamed,
        lambda r: f"placeholder {r.top_module!r}; caller may substitute its dataset default",
    )

    if unaccounted:
        print(f"UNEXPLAINED ({len(unaccounted)})")
        for report in unaccounted:
            print(f"  - {report.stem}")
        print()

    if args.verbose:
        print(f"{'stem':44} {'top':12} {'ports':>6} {'reset':16}")
        for report in reports:
            print(
                f"{report.stem:44} {str(report.top_ok):12} "
                f"{report.reference_ports:>6} "
                f"{report.reset_polarity or '-':6}{'/ _n' if report.reset_has_n_suffix else '':6}"
            )

    print(
        f"===== {len(reports)} task(s), {len(clean)} fully correct, "
        f"{len(upstream)} known upstream issue(s), {len(unnamed)} unnamed, "
        f"{len(unaccounted)} unexplained ====="
    )
    # A non-zero exit on an unexplained discrepancy is what makes this usable as
    # a gate. Recorded upstream prompt bugs and unnamed modules are not defects.
    return 1 if unaccounted else 0


if __name__ == "__main__":
    raise SystemExit(main())
