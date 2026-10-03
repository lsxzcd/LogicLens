"""Verify that generated testbenches are real graders.

Synthesis is unavailable in the DSH sandbox (Vivado's Tcl app store fails), but
the simulation half of the flow works, and that is enough to prove the point:
a generated testbench must accept a correct DUT and reject a broken one. If it
always printed TEST_PASS, both cases would pass and the abstraction would be
worthless.

Run: py -3 experiments\\tb_verify.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.task_parser import parse_task  # noqa: E402
from agent.testbench import resolve_testbench  # noqa: E402

OUT = ROOT / "experiments" / "runs" / "_tb_verify"
COUNTER_Q = ROOT / "data" / "examples" / "counter" / "question.txt"
CORRECT = ROOT / "data" / "examples" / "counter" / "answer.v"
WRONG = ROOT / "experiments" / "retest_inputs" / "answer_wrong_enable.v"

# xvlog/xelab/xsim live next to vivado and are not on PATH; the flow finds them
# because Vivado puts its bin directory on PATH for its own batch session.
from agent.vivado_runner import locate_vivado  # noqa: E402

_VIVADO = locate_vivado(None)
BIN = Path(_VIVADO).parent if _VIVADO else Path(".")
XVLOG = str(BIN / "xvlog.bat")
XELAB = str(BIN / "xelab.bat")
XSIM = str(BIN / "xsim.bat")


def simulate(rtl: Path, tb: Path, tb_top: str, work: Path) -> tuple[bool, str]:
    """Grade a DUT the same way the flow does: TEST_PASS with no failure marker."""
    work.mkdir(parents=True, exist_ok=True)
    steps = (
        ([XVLOG, "-sv", str(rtl), str(tb)], "XVLOG"),
        ([XELAB, "-debug", "typical", "-mt", "off", tb_top, "-s", "sim"], "XELAB"),
        ([XSIM, "sim", "-runall"], "XSIM"),
    )
    collected: list[str] = []
    for command, stage in steps:
        completed = subprocess.run(command, cwd=work, capture_output=True, text=True, errors="replace")
        collected.append(completed.stdout + completed.stderr)
        if completed.returncode != 0 or f"{stage}_FAILED" in collected[-1]:
            return False, f"{stage} FAILED\n" + "\n".join(collected)
    log = collected[-1]
    passed = "TEST_PASS" in log and "Fatal:" not in log and "ERROR:" not in log
    return passed, "\n".join(collected)


def run_case(label: str, rtl: Path, expect_pass: bool) -> int:
    text = COUNTER_Q.read_text(encoding="utf-8")
    contract = parse_task(text)
    spec = resolve_testbench(ROOT, COUNTER_Q, contract, rtl_text=rtl.read_text(encoding="utf-8"), mode="generated")
    work = OUT / label.replace(" ", "_")
    tb_path = spec.materialize(work)
    passed, log = simulate(rtl, tb_path, spec.top, work)
    ok = passed == expect_pass
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}: behavior={spec.behavior} source={spec.source} "
          f"expected pass={expect_pass} got pass={passed}")
    if not ok:
        print("    ---- log tail ----")
        for line in log.strip().splitlines()[-14:]:
            print("    " + line)
    return 0 if ok else 1


def main() -> int:
    failures = run_case("counter correct", CORRECT, True)
    failures += run_case("counter wrong", WRONG, False)
    print(f"\n===== {failures} failed case(s) =====")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
