from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .candidate_ranker import synthesis_credit
from .model_client import ModelClient, extract_verilog
from .repair_policy import build_baseline_prompt
from .task_parser import parse_task
from .testbench import resolve_reference_answer, resolve_testbench
from .vivado_runner import run_vivado_flow


def _default_run_dir(project_root: Path, prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return project_root / "experiments" / "runs" / f"{prefix}_{stamp}"


def run_baseline(
    project_root: Path,
    question_path: Path,
    vivado: str | None,
    mock: bool,
    run_dir: Path | None = None,
    testbench: Path | None = None,
    testbench_mode: str = "auto",
) -> dict:
    run_dir = run_dir or _default_run_dir(project_root, "baseline")
    run_dir.mkdir(parents=True, exist_ok=True)
    question = question_path.read_text(encoding="utf-8")
    contract = parse_task(question)
    if mock:
        reference = resolve_reference_answer(question_path)
        if reference is None:
            raise FileNotFoundError(
                f"--mock needs a reference implementation beside the question "
                f"({question_path.stem}.answer.v); none found for {question_path}"
            )
        code = reference.read_text(encoding="utf-8")
    else:
        prompt = build_baseline_prompt(question)
        code = extract_verilog(ModelClient().generate(prompt))
    rtl_path = run_dir / f"{contract.top_module}.v"
    shutil.copyfile(question_path, run_dir / "question.txt")
    rtl_path.write_text(code, encoding="utf-8")

    spec = resolve_testbench(
        project_root,
        question_path,
        contract,
        rtl_text=code,
        mode=testbench_mode,
        explicit=testbench,
    )
    tb_path = spec.materialize(run_dir)
    persisted_tb = run_dir / "testbench.v"
    if tb_path.resolve() != persisted_tb.resolve():
        persisted_tb.write_text(tb_path.read_text(encoding="utf-8"), encoding="utf-8")
    tb_top = spec.top or contract.testbench_top

    flow = run_vivado_flow(project_root, rtl_path, tb_path, tb_top, contract.top_module, run_dir, vivado, mock)
    result = {
        "success": bool(
            flow.get("simulation_pass")
            and synthesis_credit(flow)
            and flow.get("timing_constraint_pass", True)
        ),
        "mode": "baseline",
        "contract": contract.to_dict(),
        "testbench": {"top": tb_top, "source": spec.source, "behavior": spec.behavior, "notes": spec.notes},
        **flow,
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
