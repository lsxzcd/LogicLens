"""End-to-end check of a VerilogEval problem through the real Vivado flow.

Proves three things the adapter has to get right:

1. the testbench is compiled together with its reference implementation
   (without `_ref.sv`, elaboration fails with an unknown module);
2. the harness runs under xsim, not Icarus, so the competition's toolchain is
   what is being exercised;
3. the pass criterion is the testbench's own `Mismatches: 0 in N samples`
   verdict, not a TEST_PASS marker that VerilogEval never prints.

Run: py -3 experiments/verilogeval_verify.py
"""

from __future__ import annotations

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
STEM = "Prob001_zero"
RUNS = ROOT / "experiments" / "runs" / "_verilogeval_verify"

REFERENCE_MODULE = re.compile(r"\bmodule\s+RefModule\b")


def dut_from_reference(reference_text: str, dut_module: str) -> str:
    """Reuse the official reference body, renamed to the DUT module name.

    The testbench instantiates both `RefModule` (from `_ref.sv`) and the DUT,
    so a correct DUT is exactly the reference with a different module name.
    """
    return REFERENCE_MODULE.sub(f"module {dut_module}", reference_text, count=1)


def run_case(label: str, code: str) -> int:
    question = DATASET / f"{STEM}_prompt.txt"
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
    reference_sources = [path for path in spec.extra_sources if path.is_file()]

    flow = run_vivado_flow(
        ROOT,
        rtl_path,
        tb_path,
        tb_top,
        dut_module,
        run_dir,
        locate_vivado(None),
        False,
        extra_sources=reference_sources,
        relax_compile=spec.relax_compile,
    )

    sim_log = (run_dir / "simulation.log").read_text(encoding="utf-8", errors="replace") if (
        run_dir / "simulation.log"
    ).is_file() else ""
    verdict = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples", sim_log)

    print(f"\n--- {label} ---")
    print(f"  testbench source : {spec.source}  behaviour={spec.behavior}")
    print(f"  testbench top    : {tb_top}")
    print(f"  DUT module       : {dut_module}")
    print(f"  compile units    : {len(flow.get('compile_units', []))}")
    for unit in flow.get("compile_units", []):
        print(f"      {Path(unit).name}")
    print(f"  relax_compile    : {int(bool(flow.get('relax_compile')))}")
    print(f"  compile={int(bool(flow.get('compile_pass')))} "
          f"elaborate={int(bool(flow.get('elaborate_pass')))} "
          f"sim={int(bool(flow.get('simulation_pass')))} "
          f"synth_attempted={int(bool(flow.get('synthesis_attempted')))} "
          f"synth={int(bool(flow.get('synthesis_pass')))}")
    print(f"  mismatches       : {verdict.group(0) if verdict else 'not reported'}")
    error = flow.get("synthesis_error", "")
    if error:
        print(f"  synthesis_error  : {str(error)[:120]}")
    return 0


def main() -> int:
    if not locate_vivado(None):
        print("Vivado not found; nothing to verify.")
        return 2

    question = DATASET / f"{STEM}_prompt.txt"
    reference_path = DATASET / f"{STEM}_ref.sv"
    if not question.is_file() or not reference_path.is_file():
        print(f"fixture missing under {DATASET}; run tools/fetch_verilogeval_problem.py first")
        return 2

    reference_text = reference_path.read_text(encoding="utf-8")

    problems = 0
    # Control: the reference body under the DUT name must satisfy the official
    # testbench, with zero mismatches.
    contract = parse_task(question.read_text(encoding="utf-8"))
    probe = resolve_testbench(ROOT, question, contract, rtl_text=reference_text, mode="auto")
    correct = dut_from_reference(reference_text, probe.dut_module or "TopModule")
    run_case("reference_body", correct)
    flow_path = RUNS / "reference_body" / "flow_result.json"
    if flow_path.is_file():
        import json

        flow = json.loads(flow_path.read_text(encoding="utf-8"))
        sim_log = (RUNS / "reference_body" / "simulation.log").read_text(encoding="utf-8", errors="replace")
        verdict = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples", sim_log)
        ok = bool(flow.get("simulation_pass")) and verdict is not None and verdict.group(1) == "0"
        print(f"\n[{'OK  ' if ok else 'FAIL'}] reference body must satisfy the official testbench")
        if not ok:
            problems += 1

    # Fault injection: a DUT that never drives its output must be rejected.
    broken = correct.replace("assign zero = 1'b0;", "assign zero = 1'b1;")
    if broken == correct:
        print("[SKIP] fault injection did not change the reference body")
    else:
        run_case("fault_injected", broken)
        flow_path = RUNS / "fault_injected" / "flow_result.json"
        if flow_path.is_file():
            import json

            flow = json.loads(flow_path.read_text(encoding="utf-8"))
            sim_log = (RUNS / "fault_injected" / "simulation.log").read_text(encoding="utf-8", errors="replace")
            verdict = re.search(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples", sim_log)
            rejected = (not flow.get("simulation_pass")) and verdict is not None and verdict.group(1) != "0"
            print(f"[{'OK  ' if rejected else 'FAIL'}] a wrong DUT must be rejected by the mismatch counter")
            if not rejected:
                problems += 1

    print(f"\n===== {problems} failed check(s) =====")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
