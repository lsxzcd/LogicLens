from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .candidate_ranker import score_result, synthesis_credit
from .error_classifier import classify_error, load_patterns
from .model_client import ModelClient, extract_verilog
from .repair_policy import build_generation_prompt, build_repair_prompt
from .task_parser import parse_task
from .testbench import resolve_reference_answer, resolve_testbench
from .vivado_runner import run_vivado_flow


class LogicLensAgent:
    def __init__(
        self,
        project_root: Path,
        vivado: str | None,
        mock: bool,
        max_attempts: int = 3,
        testbench: Path | None = None,
        testbench_mode: str = "auto",
    ):
        self.project_root = project_root
        self.vivado = vivado
        self.mock = mock
        self.max_attempts = max(1, max_attempts)
        self.testbench = testbench
        self.testbench_mode = testbench_mode
        self.patterns = load_patterns(project_root / "skill" / "error_patterns.json")
        self.client = ModelClient()

    def _run_dir(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.project_root / "experiments" / "runs" / f"agent_{stamp}"

    def run(self, question_path: Path, run_dir: Path | None = None, source: str = "agent") -> dict:
        run_dir = run_dir or self._run_dir()
        run_dir.mkdir(parents=True, exist_ok=True)
        question = question_path.read_text(encoding="utf-8")
        contract = parse_task(question)
        skill_text = (self.project_root / "skill" / "rtl_rules.md").read_text(encoding="utf-8")
        history: list[dict] = []

        if self.mock:
            reference = resolve_reference_answer(question_path)
            if reference is None:
                raise FileNotFoundError(
                    f"--mock needs a reference implementation beside the question "
                    f"({question_path.stem}.answer.v); none found for {question_path}"
                )
            current_code = reference.read_text(encoding="utf-8")
        else:
            prompt = build_generation_prompt(contract, skill_text)
            current_code = extract_verilog(self.client.generate(prompt))

        # The testbench is resolved once per task, then reused for every attempt
        # so a repair is graded against exactly the same checker.
        spec = resolve_testbench(
            self.project_root,
            question_path,
            contract,
            rtl_text=current_code,
            mode=self.testbench_mode,
            explicit=self.testbench,
        )
        tb_path = spec.materialize(run_dir)
        persisted_tb = run_dir / "testbench.v"
        if tb_path.resolve() != persisted_tb.resolve():
            persisted_tb.write_text(tb_path.read_text(encoding="utf-8"), encoding="utf-8")
        tb_top = spec.top or contract.testbench_top
        # A testbench that hardcodes the module it instantiates wins over the
        # name derived from the task text; otherwise elaboration cannot bind it.
        dut_module = spec.dut_module or contract.top_module
        reference_sources = [path for path in spec.extra_sources if path.is_file()]

        best = None
        best_score = (-1, -1, -999)
        for attempt in range(1, self.max_attempts + 1):
            attempt_dir = run_dir / f"attempt_{attempt}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            rtl_path = attempt_dir / f"{dut_module}.v"
            rtl_path.write_text(current_code, encoding="utf-8")
            shutil.copyfile(question_path, attempt_dir / "question.txt")
            flow = run_vivado_flow(
                self.project_root,
                rtl_path,
                tb_path,
                tb_top,
                dut_module,
                attempt_dir,
                self.vivado,
                self.mock,
                extra_sources=reference_sources,
                relax_compile=spec.relax_compile,
            )
            verified = bool(
                flow.get("simulation_pass")
                and synthesis_credit(flow)
                and flow.get("timing_constraint_pass", True)
            )
            error_type = "none" if verified else classify_error(flow.get("log", ""), self.patterns)
            record = {"attempt": attempt, "error_type": error_type, **flow}
            history.append(record)
            current_score = score_result(flow, attempt)
            if current_score > best_score:
                best_score = current_score
                best = {"attempt": attempt, "code": current_code, **flow}
            if verified:
                break
            if attempt < self.max_attempts and not self.mock:
                repair_prompt = build_repair_prompt(contract, current_code, error_type, flow.get("log", ""), skill_text)
                current_code = extract_verilog(self.client.generate(repair_prompt))

        if best is None:
            best = {
                "attempt": 0,
                "code": current_code,
                "compile_pass": False,
                "elaborate_pass": False,
                "simulation_pass": False,
                "sim_crashed": False,
                "synthesis_attempted": False,
                "synthesis_pass": False,
                "timing_constraint_pass": False,
            }
        (run_dir / "best.v").write_text(best["code"], encoding="utf-8")
        result = {
            "success": bool(
                best.get("simulation_pass")
                and synthesis_credit(best)
                and best.get("timing_constraint_pass", True)
            ),
            "mode": "mock" if self.mock else "agent",
            "source": source,
            "contract": contract.to_dict(),
            "testbench": {
                "top": tb_top,
                "source": spec.source,
                "behavior": spec.behavior,
                "dut_module": dut_module,
                "extra_sources": [str(p) for p in reference_sources],
                "relax_compile": spec.relax_compile,
                "notes": spec.notes,
            },
            "best_attempt": best.get("attempt"),
            "compile_pass": best.get("compile_pass", False),
            "elaborate_pass": best.get("elaborate_pass", False),
            "simulation_pass": best.get("simulation_pass", False),
            "sim_crashed": best.get("sim_crashed", False),
            "synthesis_attempted": best.get("synthesis_attempted", False),
            "synthesis_pass": best.get("synthesis_pass", False),
            "timing_constraint_pass": best.get("timing_constraint_pass", False),
            "elapsed_seconds": best.get("elapsed_seconds", 0.0),
            "history": history,
        }
        (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
