"""P0.5 verification: exercise the three cases the flow changes must handle.

Not part of the unit suite because it drives real Vivado and takes minutes.
Run it explicitly:

    py -3 experiments/p05_verify.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.vivado_runner import locate_vivado, run_vivado_flow  # noqa: E402

INPUTS = ROOT / "experiments" / "p05_inputs"
RUNS = ROOT / "experiments" / "runs"
COUNTER_TB = ROOT / "data" / "examples" / "counter" / "tb.v"
WRONG_RTL = ROOT / "experiments" / "retest_inputs" / "answer_wrong_enable.v"
VIVADO = locate_vivado(None)

CASES = (
    # label, rtl, tb, tb_top, top, expectations
    (
        "p05_clocked_ok",
        ROOT / "data" / "examples" / "counter" / "answer.v",
        COUNTER_TB,
        "counter_tb",
        "counter",
        {
            "compile_pass": 1,
            "elaborate_pass": 1,
            "simulation_pass": 1,
            "sim_crashed": 0,
            "synthesis_attempted": 1,
            "synthesis_pass": 1,
            "timing_constraint_pass": 1,
            "clock_port": "clk",
        },
    ),
    (
        "p05_comb_ok",
        INPUTS / "alu_comb.v",
        INPUTS / "alu_comb_tb.v",
        "alu_comb_tb",
        "alu_comb",
        {
            "compile_pass": 1,
            "elaborate_pass": 1,
            "simulation_pass": 1,
            "sim_crashed": 0,
            "synthesis_attempted": 1,
            "synthesis_pass": 1,
            "timing_constraint_pass": 1,
            "clock_port": "",
        },
    ),
    (
        "p05_clocked_wrong",
        WRONG_RTL,
        COUNTER_TB,
        "counter_tb",
        "counter",
        {
            "compile_pass": 1,
            "elaborate_pass": 1,
            "simulation_pass": 0,
            "sim_crashed": 0,
            "synthesis_attempted": 0,
            "synthesis_pass": 0,
            "timing_constraint_pass": 0,
            "clock_port": "clk",
        },
    ),
)


def main() -> int:
    if not VIVADO:
        print("Vivado not found; nothing to verify.")
        return 2
    print(f"using vivado: {VIVADO}")
    failures = 0
    env_blocked = 0
    for label, rtl, tb, tb_top, top, expected in CASES:
        run_dir = RUNS / label
        flow = run_vivado_flow(ROOT, Path(rtl), Path(tb), tb_top, top, run_dir, VIVADO, False)
        print(f"\n===== {label} =====")
        print(json.dumps({k: flow.get(k) for k in expected}, ensure_ascii=False))
        # A sandbox that blocks Vivado's Tcl app store makes read_xdc and
        # synth_design fail for environmental reasons. Report that separately
        # so it is never mistaken for a design or flow defect.
        blocked = (
            flow.get("synthesis_attempted")
            and not flow.get("synthesis_pass")
            and "tclapp" in str(flow.get("synthesis_error", ""))
        )
        for key, want in expected.items():
            got = flow.get(key)
            if got == want:
                print(f"  OK   {key}: {got!r}")
            elif blocked and key in ("synthesis_pass", "timing_constraint_pass"):
                print(f"  ENV  {key}: expected {want!r}, got {got!r} (Vivado Tcl app store blocked here)")
            else:
                failures += 1
                print(f"  FAIL {key}: expected {want!r}, got {got!r}")
        if blocked:
            env_blocked += 1
            print(f"  note: {flow.get('synthesis_error')}")
    print(f"\n===== {len(CASES)} cases, {failures} failed assertion(s), {env_blocked} env-blocked =====")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
