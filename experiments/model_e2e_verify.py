"""End-to-end check of the model call path with a real Vivado run.

Starts the stub model server in a background thread, points the agent at it,
and has the candidate it returns graded by the official VerilogEval testbench
under xsim. The stub is not a model: it returns a canned reply. What this proves
is that everything around the model works - the request shape, the configured
sampling, extraction of the code block, the verdict path, and the attribution of
a failure to the right stage - which is the part that otherwise only fails in
the middle of an evaluation run.

Run: py -3 experiments/model_e2e_verify.py [--port 8799]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import stub_model_server  # noqa: E402

from agent.controller import LogicLensAgent  # noqa: E402
from agent.model_client import ModelClient  # noqa: E402
from agent.vivado_runner import locate_vivado  # noqa: E402

QUESTION = ROOT / "experiments" / "data" / "verilogeval" / "examples" / "Prob001_zero_prompt.txt"
RUN_DIR = ROOT / "experiments" / "runs" / "_model_e2e"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()

    if not locate_vivado(None):
        print("Vivado not found; nothing to verify.")
        return 2
    if not QUESTION.is_file():
        print(f"fixture missing: {QUESTION}")
        return 2

    server, _ = stub_model_server.serve(args.port)
    print(f"stub model server on http://127.0.0.1:{args.port}/v1")
    failures = 0

    try:
        if RUN_DIR.exists():
            shutil.rmtree(RUN_DIR, ignore_errors=True)

        client = ModelClient(
            url=f"http://127.0.0.1:{args.port}/v1",
            model="stub-coder",
            seed=1,
            temperature=0.2,
        )
        agent = LogicLensAgent(
            project_root=ROOT,
            vivado=None,
            mock=False,
            max_attempts=3,
            model_client=client,
        )
        result = agent.run(QUESTION, run_dir=RUN_DIR, source="e2e-stub")

        print()
        print("--- result ---")
        print(f"  model endpoint : {result['model']['endpoint']}")
        print(f"  sampling       : temperature={result['model']['temperature']} seed={result['model']['seed']}")
        print(f"  compile        : {int(bool(result['compile_pass']))}")
        print(f"  simulation     : {int(bool(result['simulation_pass']))}")
        print(f"  synth attempted: {int(bool(result['synthesis_attempted']))}")
        print(f"  synth pass     : {int(bool(result['synthesis_pass']))}")
        print(f"  stopped early  : {result.get('stopped_early')!r}")
        for record in result["history"]:
            print(
                f"  attempt {record['attempt']}: failed_stage={record.get('failed_stage')!r} "
                f"error_type={record['error_type']!r} mismatches={record.get('sim_mismatches')!r}"
            )

        # The stub returns a correct implementation for this task, so the
        # official testbench must accept it with zero mismatches.
        accepted = bool(result["simulation_pass"]) and result["history"][0].get("sim_mismatches") == "0"
        print(f"\n[{'OK  ' if accepted else 'FAIL'}] stub reply was graded as a correct design")
        if not accepted:
            failures += 1

        # The failure stage must be reported as synthesis (the sandbox blocks
        # it) and never as a simulation mismatch, which would send the repair
        # loop after a problem that does not exist.
        first = result["history"][0]
        if first.get("simulation_pass"):
            stage_ok = first.get("failed_stage") == "synthesis"
            type_ok = first["error_type"] != "simulation_mismatch"
            print(f"[{'OK  ' if stage_ok else 'FAIL'}] a passing simulation is attributed to synthesis")
            print(f"[{'OK  ' if type_ok else 'FAIL'}] the failure is not reported as a simulation mismatch")
            failures += 0 if stage_ok else 1
            failures += 0 if type_ok else 1

        # A toolchain failure cannot be fixed by resampling, so only one attempt
        # should have been made.
        single = len(result["history"]) == 1
        print(f"[{'OK  ' if single else 'FAIL'}] a toolchain failure did not trigger retries "
              f"({len(result['history'])} attempt(s))")
        if not single:
            failures += 1

        (RUN_DIR / "e2e_summary.json").write_text(
            json.dumps(
                {
                    "accepted_by_official_testbench": accepted,
                    "attempts": len(result["history"]),
                    "failed_stage": first.get("failed_stage"),
                    "error_type": first["error_type"],
                    "model": result["model"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        server.shutdown()
        server.server_close()

    print(f"\n===== {failures} failed check(s) =====")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
