"""End-to-end verification of the pipeline with real Vivado.

Unlike a `--mock` run, this drives the real toolchain and reports the actual
per-stage outcome, so it proves the generated and sidecar testbenches really
verify candidates through the same path the agent uses.

Synthesis is unavailable in the DSH sandbox (Vivado's Tcl app store fails), so
the synthesis column is expected to be reported as ENV here; the simulation
column is the meaningful signal.

Run: py -3 experiments\\pipeline_verify.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.task_parser import parse_task  # noqa: E402
from agent.testbench import resolve_reference_answer, resolve_testbench  # noqa: E402
from agent.vivado_runner import locate_vivado, run_vivado_flow  # noqa: E402

DATASET = ROOT / "experiments" / "dataset_smoke"
RUNS = ROOT / "experiments" / "runs" / "_pipeline_verify"


def run_task(task_stem: str, submit_broken: bool) -> int:
    question = DATASET / f"{task_stem}.txt"
    text = question.read_text(encoding="utf-8")
    contract = parse_task(text)
    reference = resolve_reference_answer(question)
    if reference is None:
        print(f"[FAIL] {task_stem}: no sidecar reference answer")
        return 1

    code = reference.read_text(encoding="utf-8")
    if submit_broken:
        # A syntactic defect: the design cannot compile, so the pipeline must
        # report failure at the first stage rather than reach simulation.
        code = code.rstrip() + "\n\n    assign this_line_is_not_valid_verilog = ;\n"

    spec = resolve_testbench(ROOT, question, contract, rtl_text=code, mode="auto")
    label = f"{task_stem}_{'broken' if submit_broken else 'ok'}"
    run_dir = RUNS / label
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    tb_path = spec.materialize(run_dir)
    rtl_path = run_dir / f"{contract.top_module}.v"
    rtl_path.write_text(code, encoding="utf-8")
    tb_top = spec.top or contract.testbench_top

    flow = run_vivado_flow(ROOT, rtl_path, tb_path, tb_top, contract.top_module, run_dir, locate_vivado(None), False)
    compile_ok = bool(flow.get("compile_pass"))
    sim = bool(flow.get("simulation_pass"))
    synth_attempted = bool(flow.get("synthesis_attempted"))
    blocked = "tclapp" in str(flow.get("synthesis_error", ""))
    print(
        f"[{task_stem}] tb={spec.source}/{spec.behavior} compile={int(compile_ok)} "
        f"elaborate={int(bool(flow.get('elaborate_pass')))} sim={int(sim)} "
        f"synth_attempted={int(synth_attempted)} synth={int(bool(flow.get('synthesis_pass')))}"
        + (" (synth ENV-blocked)" if blocked else "")
    )
    if submit_broken:
        # A broken design must fail at compilation and must not be credited
        # with simulation or synthesis.
        return 0 if (not compile_ok and not sim and not synth_attempted) else 1
    # A correct design must simulate, and synthesis must have been attempted.
    return 0 if (compile_ok and sim and synth_attempted) else 1


def main() -> int:
    if not locate_vivado(None):
        print("Vivado not found; nothing to verify.")
        return 2
    failures = run_task("counter", submit_broken=False)
    failures += run_task("counter", submit_broken=True)
    failures += run_task("alu_comb", submit_broken=False)
    failures += run_task("alu_comb", submit_broken=True)
    print(f"\n===== {failures} failed case(s) =====")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
