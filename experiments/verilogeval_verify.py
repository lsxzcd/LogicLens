"""Run a whole VerilogEval fixture dataset through the real Vivado flow.

For every task it does two things:

* builds a DUT from the official reference body and requires the official
  testbench to accept it (proving the adapter drives that task correctly);
* flips the design so its output differs, and requires the testbench to reject
  it (proving the check is real and not a testbench that always passes).

Sequential tasks are the interesting ones: their testbench generates the clock
while the DUT has no clock port at all, which exercises the XDC path
differently from a purely combinational task.

Run:
    py -3 experiments/verilogeval_verify.py                 # every task found
    py -3 experiments/verilogeval_verify.py Prob090_circuit1
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.task_parser import parse_task  # noqa: E402
from agent.testbench import resolve_testbench  # noqa: E402
from agent.vivado_runner import locate_vivado, run_vivado_flow  # noqa: E402

DATASET = ROOT / "experiments" / "data" / "verilogeval" / "examples"
RUNS = ROOT / "experiments" / "runs" / "_verilogeval_dataset"

REFERENCE_MODULE = re.compile(r"\bmodule\s+RefModule\b")
VERDICT = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")


def dut_from_reference(reference_text: str, dut_module: str) -> str:
    """Reuse the official reference body, renamed to the DUT module name.

    The testbench instantiates `RefModule` (from the sibling file) and the DUT,
    so a correct DUT is exactly the reference under a different name.
    """
    return REFERENCE_MODULE.sub(f"module {dut_module}", reference_text, count=1)


def environment_blocked(flow: dict) -> bool:
    """True when synthesis failed for a host reason, not a design defect.

    A sandboxed shell can leave Vivado's Tcl app store unusable, which makes
    read_xdc and synth_design fail for reasons unrelated to the netlist.
    """
    return "tclapp" in str(flow.get("synthesis_error", ""))


# A cheap, widely applicable corruption: invert the constant in an assignment.
INVERT_ASSIGN = re.compile(r"assign\s+(\w+)\s*=\s*1'b([01])\s*;")
# Any continuous assignment, so its right-hand side can be negated.
ANY_CONTINUOUS = re.compile(r"assign\s+([A-Za-z_]\w*)\s*=\s*([^;]+);")
# Declaration of an output port, used as a last resort.
FIRST_OUTPUT = re.compile(r"\boutput\s+(?:reg|wire)?\s*(?:\[[^\]]*\]\s*)?(\w+)", re.I)


def corrupt(text: str) -> tuple[str, str] | None:
    """Introduce a behavioural difference, or return None when none applies.

    Only corruptions that are certain to change the simulated value are used.
    Driving an output that an `always`/`always_comb` block already drives was
    tried and rejected: it produces a multi-driver X, and the VerilogEval
    comparison deliberately lets an X on the reference side match anything, so
    such a corruption can pass and would make this check report a false
    failure. Negating a continuous assignment cannot have that problem.
    """
    match = INVERT_ASSIGN.search(text)
    if match:
        flipped = "1" if match.group(2) == "0" else "0"
        return text[: match.start(2)] + flipped + text[match.end(2) :], f"inverted constant on {match.group(1)}"

    output_names = set(re.findall(r"\boutput\s+(?:reg|wire)?\s*(?:\[[^\]]*\]\s*)?(\w+)", text, re.I))
    for candidate in ANY_CONTINUOUS.finditer(text):
        name, expression = candidate.group(1), candidate.group(2).strip()
        if name not in output_names or not expression:
            continue
        if expression.startswith("~"):
            replacement = expression[1:].strip()
            description = f"removed inversion on {name}"
        else:
            replacement = f"~({expression})"
            description = f"negated continuous assign on {name}"
        return text[: candidate.start(2)] + replacement + text[candidate.end(2) :], description

    return None


def run_one(question: Path, code: str, label: str) -> dict:
    contract = parse_task(question.read_text(encoding="utf-8"))
    spec = resolve_testbench(ROOT, question, contract, rtl_text=code, mode="auto")
    dut_module = spec.dut_module or contract.top_module
    tb_top = spec.top or contract.testbench_top

    run_dir = RUNS / label
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    tb_path = spec.materialize(run_dir)
    rtl_path = run_dir / f"{dut_module}.v"
    rtl_path.write_text(code, encoding="utf-8")

    flow = run_vivado_flow(
        ROOT,
        rtl_path,
        tb_path,
        tb_top,
        dut_module,
        run_dir,
        locate_vivado(None),
        False,
        extra_sources=[p for p in spec.extra_sources if p.is_file()],
        relax_compile=spec.relax_compile,
    )
    sim_log_path = run_dir / "simulation.log"
    sim_log = sim_log_path.read_text(encoding="utf-8", errors="replace") if sim_log_path.is_file() else ""
    verdict = VERDICT.search(sim_log)
    return {
        "flow": flow,
        "mismatches": verdict.group(1) if verdict else None,
        "samples": verdict.group(2) if verdict else None,
        "dut_module": dut_module,
        "tb_top": tb_top,
        "relax": bool(flow.get("relax_compile")),
        "tb_source": spec.source,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stems", nargs="*", help="Problem stems; default is every task found")
    args = parser.parse_args()

    if not locate_vivado(None):
        print("Vivado not found; nothing to verify.")
        return 2

    if args.stems:
        questions = [DATASET / f"{stem}_prompt.txt" for stem in args.stems]
    else:
        questions = sorted(DATASET.glob("*_prompt.txt"))

    if not questions:
        print(f"no tasks found under {DATASET}")
        print("run: py -3 tools/fetch_verilogeval_problem.py <stem> experiments/data/verilogeval")
        return 2

    problems = 0
    rows: list[dict] = []
    notes: list[str] = []

    for question in questions:
        if not question.is_file():
            print(f"[SKIP] {question.name} not found")
            continue
        stem = question.stem[: -len("_prompt")] if question.stem.endswith("_prompt") else question.stem
        reference_path = question.with_name(f"{stem}_ref.sv")
        if not reference_path.is_file():
            print(f"[SKIP] {stem}: no reference implementation")
            continue

        reference_text = reference_path.read_text(encoding="utf-8")
        contract = parse_task(question.read_text(encoding="utf-8"))
        probe = resolve_testbench(ROOT, question, contract, rtl_text=reference_text, mode="auto")
        correct = dut_from_reference(reference_text, probe.dut_module or "TopModule")

        print(f"\n=== {stem} ===")
        good = run_one(question, correct, f"{stem}__ok")
        flow = good["flow"]
        accepted = bool(flow.get("simulation_pass")) and good["mismatches"] == "0"
        blocked = environment_blocked(flow)
        if not flow.get("synthesis_attempted"):
            synth = "skip"
        elif flow.get("synthesis_pass"):
            synth = "ok"
        elif blocked:
            synth = "ENV"
        else:
            synth = "FAIL"
        print(
            f"  [{'OK  ' if accepted else 'FAIL'}] reference accepted   "
            f"compile={int(bool(flow.get('compile_pass')))} "
            f"elab={int(bool(flow.get('elaborate_pass')))} "
            f"sim={int(bool(flow.get('simulation_pass')))} synth={synth}  "
            f"mismatches={good['mismatches']}/{good['samples']}  "
            f"clock_port={flow.get('clock_port', '')!r}{'  relax' if good['relax'] else ''}"
        )
        if not accepted:
            problems += 1
            error = flow.get("synthesis_error", "")
            if error:
                print(f"        synthesis_error: {str(error)[:160]}")

        corrupted = corrupt(correct)
        rejected = None
        injection = ""
        if corrupted is None:
            notes.append(f"{stem}: no reliable fault injection available")
            print("  [SKIP] no reliable fault injection for this design (not counted as a failure)")
        else:
            broken_text, injection = corrupted
            bad = run_one(question, broken_text, f"{stem}__bad")
            bad_flow = bad["flow"]
            rejected = (not bad_flow.get("simulation_pass")) and bad["mismatches"] not in (None, "0")
            print(
                f"  [{'OK  ' if rejected else 'FAIL'}] corrupted rejected    "
                f"({injection})  sim={int(bool(bad_flow.get('simulation_pass')))} "
                f"mismatches={bad['mismatches']}/{bad['samples']}"
            )
            if not rejected:
                problems += 1

        rows.append(
            {
                "stem": stem,
                "accepted": accepted,
                "rejected": rejected,
                "injection": injection,
                "compile": bool(flow.get("compile_pass")),
                "elaborate": bool(flow.get("elaborate_pass")),
                "synthesis_attempted": bool(flow.get("synthesis_attempted")),
                "synthesis": bool(flow.get("synthesis_pass")),
                "synthesis_env_blocked": blocked,
                "clock_port": flow.get("clock_port", ""),
                "relax": good["relax"],
                "mismatches": good["mismatches"],
                "samples": good["samples"],
            }
        )

    RUNS.mkdir(parents=True, exist_ok=True)
    summary_path = RUNS / "summary.json"
    summary_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 汇总 =====")
    print(f"{'task':40} {'compile':8} {'elab':6} {'sim':6} {'synth':6} {'clk':5} {'mismatch':10} {'reject':7}")
    for row in rows:
        if not row["synthesis_attempted"]:
            synth = "skip"
        elif row["synthesis"]:
            synth = "ok"
        elif row["synthesis_env_blocked"]:
            synth = "ENV"
        else:
            synth = "FAIL"
        reject = "skip" if row["rejected"] is None else str(row["rejected"])
        print(
            f"{row['stem']:40} {str(row['compile']):8} {str(row['elaborate']):6} "
            f"{str(row['accepted']):6} {synth:6} {(row['clock_port'] or '-'):5} "
            f"{str(row['mismatches']) + '/' + str(row['samples']):10} {reject:7}"
        )
    print(f"\nsummary written to {summary_path}")
    for note in notes:
        print(f"  note: {note}")
    print(f"===== {len(rows)} task(s), {problems} failed check(s) =====")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
