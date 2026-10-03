from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

from agent.candidate_ranker import score_result, synthesis_credit
from agent.error_classifier import classify_error
from agent.evaluation import discover_tasks, pass_at_k, summarize
from agent.model_client import extract_verilog
from agent.repair_policy import build_baseline_prompt, build_generation_prompt
from agent.task_parser import parse_task, ports_from_rtl
from agent.testbench import (
    candidate_stems,
    detect_dut_module,
    detect_tb_module,
    detect_verilogeval_pass_criterion,
    resolve_testbench,
)
from agent.vivado_runner import run_vivado_flow


class TaskParserTests(unittest.TestCase):
    def test_chinese_counter_contract(self) -> None:
        contract = parse_task("顶层模块名为 pulse_counter，rst_n 为低有效复位，clk 为时钟。")
        self.assertEqual(contract.top_module, "pulse_counter")
        self.assertEqual(contract.testbench_top, "pulse_counter_tb")
        self.assertEqual(contract.reset, "rst_n")


class ModelOutputTests(unittest.TestCase):
    def test_extract_fenced_verilog(self) -> None:
        output = "说明\n```verilog\nmodule demo; endmodule\n```"
        self.assertEqual(extract_verilog(output), "module demo; endmodule")


class ErrorClassifierTests(unittest.TestCase):
    def test_classifies_width_error(self) -> None:
        patterns = {"width_mismatch": ["width mismatch"], "syntax": ["syntax error"]}
        self.assertEqual(classify_error("ERROR: width mismatch on port", patterns), "width_mismatch")

    def test_does_not_classify_bare_reset_word(self) -> None:
        patterns = json.loads((Path(__file__).parents[1] / "skill" / "error_patterns.json").read_text(encoding="utf-8"))
        self.assertEqual(classify_error("ERROR: syntax error near reset_n", patterns), "syntax")

    def test_classifies_timing_error(self) -> None:
        patterns = json.loads((Path(__file__).parents[1] / "skill" / "error_patterns.json").read_text(encoding="utf-8"))
        self.assertEqual(classify_error("WARNING: unconstrained path remains", patterns), "timing")


class SynthesisCreditTests(unittest.TestCase):
    """Synthesis is gated on simulation, so a skipped synthesis must never be
    credited as a pass when per-level pass rates are computed."""

    def test_skipped_synthesis_is_not_credited(self) -> None:
        flow = {"simulation_pass": False, "synthesis_attempted": False, "synthesis_pass": False}
        self.assertFalse(synthesis_credit(flow))

    def test_attempted_and_passed_synthesis_is_credited(self) -> None:
        flow = {"simulation_pass": True, "synthesis_attempted": True, "synthesis_pass": True}
        self.assertTrue(synthesis_credit(flow))

    def test_attempted_but_failed_synthesis_is_not_credited(self) -> None:
        flow = {"simulation_pass": True, "synthesis_attempted": True, "synthesis_pass": False}
        self.assertFalse(synthesis_credit(flow))

    def test_results_predating_the_field_keep_their_meaning(self) -> None:
        self.assertTrue(synthesis_credit({"synthesis_pass": True}))

    def test_skipped_synthesis_scores_below_a_simulation_pass(self) -> None:
        skipped = score_result({"compile_pass": 1, "elaborate_pass": 1, "simulation_pass": 1, "synthesis_attempted": 0, "synthesis_pass": 0}, 1)
        passed = score_result({"compile_pass": 1, "elaborate_pass": 1, "simulation_pass": 1, "synthesis_attempted": 1, "synthesis_pass": 1}, 2)
        self.assertGreater(passed, skipped)


class ContractExtractionTests(unittest.TestCase):
    """The contract must be derived from the task text, not assumed."""

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.counter_question = (self.root / "data" / "examples" / "counter" / "question.txt").read_text(encoding="utf-8")

    def test_counter_contract_fields(self) -> None:
        contract = parse_task(self.counter_question)
        self.assertEqual(contract.top_module, "counter")
        self.assertEqual(contract.clock_spec.name, "clk")
        self.assertEqual(contract.reset_spec.name, "rst_n")
        self.assertEqual(contract.reset_spec.polarity, "low")
        self.assertEqual(contract.reset_spec.style, "sync")
        self.assertIn("enable_hold", contract.boundaries)

    def test_counter_ports_and_widths(self) -> None:
        contract = parse_task(self.counter_question)
        widths = {p.name: p.width for p in contract.ports}
        self.assertEqual(widths.get("count"), 8)
        self.assertEqual(widths.get("enable"), 1)
        self.assertEqual(contract.direction_of("count"), "output")
        self.assertEqual(contract.direction_of("clk"), "input")

    def test_width_does_not_leak_to_a_neighbouring_port(self) -> None:
        contract = parse_task("Create a decoder with 3-bit input sel and 8-bit output y.")
        widths = {p.name: p.width for p in contract.ports}
        self.assertEqual(widths.get("sel"), 3)
        self.assertEqual(widths.get("y"), 8)

    def test_module_named_clause_is_not_confused_with_prose(self) -> None:
        contract = parse_task("Design an 8-bit up counter. Module named up_counter. Inputs: clk, rst_n, en.")
        self.assertEqual(contract.top_module, "up_counter")

    def test_prose_module_name_is_not_read_as_is(self) -> None:
        # "module name is X" must yield X. A "named?" pattern also matches the
        # bare word "name" and would capture "is" instead.
        contract = parse_task("Implement module alu_comb with inputs a, b and sub, output y.")
        self.assertEqual(contract.top_module, "alu_comb")
        contract = parse_task("4. top-level module name is alu_comb.")
        self.assertEqual(contract.top_module, "alu_comb")

    def test_verilog_module_header_is_parsed(self) -> None:
        contract = parse_task("Provide a module fifo (input wire clk, input wire [7:0] din, output reg [7:0] dout);")
        self.assertEqual(contract.top_module, "fifo")

    def test_prose_port_group_requires_a_marker(self) -> None:
        # "with ... input sel" is a sentence, not a port group: the prose parser
        # must not consume it. The explicit direction is still honoured by the
        # keyword-declaration parser, so no second invented port appears.
        contract = parse_task("Create a decoder with 3-bit input sel.")
        self.assertEqual([(p.name, p.direction, p.width) for p in contract.ports], [("sel", "input", 3)])

    def test_explicit_port_group_is_parsed(self) -> None:
        contract = parse_task("A module has input ports clk and rst_n, output ports q and valid.")
        self.assertEqual(
            [(p.name, p.direction) for p in contract.ports],
            [("clk", "input"), ("rst_n", "input"), ("q", "output"), ("valid", "output")],
        )

    def test_rtl_interface_round_trip(self) -> None:
        rtl = (self.root / "data" / "examples" / "counter" / "answer.v").read_text(encoding="utf-8")
        ports = ports_from_rtl(rtl)
        self.assertEqual(
            [(p.name, p.direction, p.width) for p in ports],
            [("clk", "input", 1), ("rst_n", "input", 1), ("enable", "input", 1), ("count", "output", 8)],
        )

    def test_unparseable_task_yields_no_invented_ports(self) -> None:
        contract = parse_task("Do something interesting with hardware, please.")
        self.assertEqual(contract.ports, [])


class TestbenchResolutionTests(unittest.TestCase):
    """This is the seam that used to be a hardcoded counter testbench path."""

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.question = self.root / "data" / "examples" / "counter" / "question.txt"
        self.question_text = self.question.read_text(encoding="utf-8")
        self.rtl = (self.root / "data" / "examples" / "counter" / "answer.v").read_text(encoding="utf-8")

    def test_generated_counter_testbench_is_self_checking(self) -> None:
        contract = parse_task(self.question_text)
        spec = resolve_testbench(self.root, self.question, contract, rtl_text=self.rtl, mode="generated")
        self.assertEqual(spec.behavior, "counter")
        self.assertTrue(spec.is_generated)
        self.assertIn("TEST_PASS", spec.text)
        self.assertIn("counter_tb", spec.text)
        # The hold requirement must be exercised, or a module that ignores
        # enable would be accepted.
        self.assertIn("changed while enable was low", spec.text)
        self.assertIn("enable = 1'b1;", spec.text)

    def test_sidecar_testbench_wins_over_generation(self) -> None:
        dataset = self.root / "experiments" / "dataset_smoke"
        question = dataset / "alu_comb.txt"
        contract = parse_task(question.read_text(encoding="utf-8"))
        spec = resolve_testbench(self.root, question, contract, rtl_text="", mode="auto")
        self.assertEqual(spec.source, "sidecar")
        self.assertEqual(spec.path.name, "alu_comb.tb.v")

    def test_explicit_testbench_wins_over_everything(self) -> None:
        explicit = self.root / "experiments" / "dataset_smoke" / "alu_comb.tb.v"
        contract = parse_task(self.question_text)
        spec = resolve_testbench(
            self.root, self.question, contract, rtl_text=self.rtl, mode="auto", explicit=explicit
        )
        self.assertEqual(spec.source, "explicit")
        self.assertEqual(spec.path, explicit)

    def test_missing_explicit_testbench_is_an_error(self) -> None:
        contract = parse_task(self.question_text)
        with self.assertRaises(FileNotFoundError):
            resolve_testbench(
                self.root,
                self.question,
                contract,
                rtl_text=self.rtl,
                mode="auto",
                explicit=self.root / "does_not_exist.tb.v",
            )

    def test_generated_testbench_is_materialized_to_a_real_file(self) -> None:
        contract = parse_task(self.question_text)
        spec = resolve_testbench(self.root, self.question, contract, rtl_text=self.rtl, mode="generated")
        target = Path(__file__).resolve().parents[1] / "experiments" / "runs" / "_unittest_tb"
        self.addCleanup(shutil.rmtree, target, True)
        written = spec.materialize(target)
        self.assertTrue(written.is_file())
        self.assertIn("module", written.read_text(encoding="utf-8"))

    def test_no_ports_yields_an_inconclusive_testbench(self) -> None:
        """It must never print TEST_PASS, so it cannot report a false success."""
        contract = parse_task("Do something interesting with hardware, please.")
        spec = resolve_testbench(
            self.root,
            self.question,
            contract,
            rtl_text="module m; endmodule",
            mode="generated",
        )
        self.assertEqual(spec.behavior, "inconclusive")
        self.assertNotIn("TEST_PASS", spec.text)


class PassAtKTests(unittest.TestCase):
    """pass@k is the headline metric, so its edge cases are pinned down."""

    def test_perfect_task_is_one(self) -> None:
        self.assertAlmostEqual(pass_at_k([True, True, True], 1, 3), 1.0)

    def test_never_solved_task_is_zero(self) -> None:
        self.assertAlmostEqual(pass_at_k([False, False, False], 1, 3), 0.0)

    def test_single_success_out_of_five_at_k1(self) -> None:
        self.assertAlmostEqual(pass_at_k([True, False, False, False, False], 1, 5), 1 / 5)

    def test_single_success_out_of_five_at_k5(self) -> None:
        self.assertAlmostEqual(pass_at_k([True, False, False, False, False], 5, 5), 1.0)

    def test_k_larger_than_samples_is_clamped(self) -> None:
        self.assertAlmostEqual(pass_at_k([True, False], 5, 2), 1.0)

    def test_empty_outcomes_is_zero(self) -> None:
        self.assertAlmostEqual(pass_at_k([], 1, 0), 0.0)

    def test_summarize_reports_every_k(self) -> None:
        rows = [
            {"task_id": "a", "success": 1, "compile_pass": 1, "elaborate_pass": 1, "simulation_pass": 1,
             "synthesis_pass": 1, "synthesis_attempted": 1, "sim_crashed": 0, "elapsed_seconds": 1.0, "error_type": ""},
            {"task_id": "a", "success": 0, "compile_pass": 1, "elaborate_pass": 1, "simulation_pass": 1,
             "synthesis_pass": 0, "synthesis_attempted": 1, "sim_crashed": 0, "elapsed_seconds": 3.0, "error_type": ""},
            {"task_id": "b", "success": 0, "compile_pass": 0, "elaborate_pass": 0, "simulation_pass": 0,
             "synthesis_pass": 0, "synthesis_attempted": 0, "sim_crashed": 0, "elapsed_seconds": 2.0, "error_type": "syntax"},
        ]
        summary = summarize(rows, 2)
        self.assertEqual(summary["tasks"], 2)
        self.assertEqual(summary["runs"], 3)
        # Rates are published rounded to four decimals.
        self.assertAlmostEqual(summary["pass@1"], 0.25, places=4)
        self.assertAlmostEqual(summary["pass@2"], 0.5, places=4)
        self.assertAlmostEqual(summary["task_success_rate"], 0.5, places=4)
        self.assertAlmostEqual(summary["success_rate"], 1 / 3, places=4)
        self.assertAlmostEqual(summary["compile_pass_rate"], 2 / 3, places=4)
        self.assertEqual(summary["synthesis_skipped_runs"], 1)
        self.assertAlmostEqual(summary["mean_elapsed_seconds"], 2.0, places=4)
        self.assertEqual(summary["error_types"], {"syntax": 1})


class EvaluationDiscoveryTests(unittest.TestCase):
    def test_discovers_tasks_and_ignores_sidecar_prompts(self) -> None:
        dataset = Path(__file__).resolve().parents[1] / "experiments" / "dataset_smoke"
        tasks = discover_tasks(dataset)
        self.assertEqual([t.task_id for t in tasks], ["alu_comb", "counter"])

    def test_missing_dataset_is_an_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            discover_tasks(Path(__file__).resolve().parents[1] / "experiments" / "no_such_dataset")


class DatasetValidatorTests(unittest.TestCase):
    """tools/check_dataset.py is what a teammate runs after exporting a dataset."""

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(self.root / "tools"))
        import check_dataset  # noqa: PLC0415

        self.module = check_dataset

    def test_finds_both_smoke_tasks(self) -> None:
        dataset = self.root / "experiments" / "dataset_smoke"
        self.assertEqual(self.module.task_stems(dataset), ["alu_comb", "counter"])

    def test_accepts_the_bundled_dataset(self) -> None:
        import subprocess  # noqa: PLC0415

        completed = subprocess.run(
            [sys.executable, str(self.root / "tools" / "check_dataset.py"), str(self.root / "experiments" / "dataset_smoke")],
            capture_output=True,
            text=True,
            errors="replace",
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("layout is valid", completed.stdout)

    def test_strict_mode_fails_without_sidecar_testbenches(self) -> None:
        import subprocess  # noqa: PLC0415

        completed = subprocess.run(
            [
                sys.executable,
                str(self.root / "tools" / "check_dataset.py"),
                str(self.root / "experiments" / "dataset_smoke"),
                "--require-testbench",
            ],
            capture_output=True,
            text=True,
            errors="replace",
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("FAILED", completed.stdout)

    def test_missing_directory_reports_an_error(self) -> None:
        import subprocess  # noqa: PLC0415

        completed = subprocess.run(
            [sys.executable, str(self.root / "tools" / "check_dataset.py"), str(self.root / "no_such_dir")],
            capture_output=True,
            text=True,
            errors="replace",
        )
        self.assertEqual(completed.returncode, 2)


class VerilogEvalAdapterTests(unittest.TestCase):
    """The VerilogEval sidecar convention is what makes 156 real testbenches usable.

    Its shape differs from this project's own examples in four ways, each of
    which broke the adapter during development: the prompt file is named
    `<stem>_prompt.txt`, the testbench is `<stem>_test.sv` whose top module is
    `tb`, it hardcodes the DUT name `TopModule`, and it needs a separate
    reference file plus a relaxed analyzer.
    """

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.fixtures = self.root / "experiments" / "data" / "verilogeval" / "examples"
        self.prompt = self.fixtures / "Prob001_zero_prompt.txt"
        self.testbench = self.fixtures / "Prob001_zero_test.sv"
        if not self.testbench.is_file():
            self.skipTest("VerilogEval fixture not present; run tools/fetch_verilogeval_problem.py")
        self.text = self.testbench.read_text(encoding="utf-8")

    def test_prompt_stem_suffix_is_stripped_for_sidecars(self) -> None:
        # The key bug: `<stem>_prompt.txt` would otherwise look for
        # `Prob001_zero_prompt_test.sv`, which does not exist.
        self.assertEqual(candidate_stems(self.prompt), ["Prob001_zero_prompt", "Prob001_zero"])

    def test_sidecar_testbench_and_reference_are_found(self) -> None:
        spec = resolve_testbench(self.root, self.prompt, parse_task(self.prompt.read_text(encoding="utf-8")))
        self.assertEqual(spec.source, "sidecar")
        self.assertEqual(spec.path.name, "Prob001_zero_test.sv")
        self.assertEqual([p.name for p in spec.extra_sources], ["Prob001_zero_ref.sv"])

    def test_dut_module_is_detected_despite_the_reference_coming_first(self) -> None:
        # `RefModule good1` appears before `TopModule top_module1`; a search that
        # stops at the first instantiation returns nothing.
        self.assertEqual(detect_dut_module(self.text), "TopModule")

    def test_testbench_top_is_the_module_instantiating_the_dut(self) -> None:
        self.assertEqual(detect_tb_module(self.text), "tb")

    def test_mismatch_criterion_is_recognised(self) -> None:
        self.assertTrue(detect_verilogeval_pass_criterion(self.text))
        # And not on an ordinary generated testbench.
        self.assertFalse(detect_verilogeval_pass_criterion("module t; initial begin $display(\"TEST_PASS\"); end endmodule"))

    def test_relaxed_compile_is_requested_for_this_testbench(self) -> None:
        spec = resolve_testbench(self.root, self.prompt, parse_task(self.prompt.read_text(encoding="utf-8")))
        self.assertTrue(spec.relax_compile)
        self.assertEqual(spec.behavior, "reference-compare")
        self.assertEqual(spec.dut_module, "TopModule")
        self.assertEqual(spec.top, "tb")

    def test_generated_testbench_does_not_request_relaxed_compile(self) -> None:
        dataset = self.root / "experiments" / "dataset_smoke"
        question = dataset / "counter.txt"
        contract = parse_task(question.read_text(encoding="utf-8"))
        rtl = (dataset / "counter.answer.v").read_text(encoding="utf-8")
        spec = resolve_testbench(self.root, question, contract, rtl_text=rtl, mode="generated")
        self.assertFalse(spec.relax_compile)
        self.assertEqual(spec.extra_sources, [])


class BaselinePromptTests(unittest.TestCase):
    """The gain baseline must carry the question and nothing else."""

    def test_baseline_prompt_is_the_question_verbatim(self) -> None:
        question = "设计一个 8 位同步计数器。\n要求：clk 上升沿触发。\n"
        self.assertEqual(build_baseline_prompt(question), question)

    def test_baseline_prompt_adds_no_guidance(self) -> None:
        prompt = build_baseline_prompt("Design a D flip-flop.")
        for leak in ("synthesizable", "Rules:", "contract", "verilog"):
            self.assertNotIn(leak, prompt.lower())

    def test_agent_prompt_is_richer_than_baseline(self) -> None:
        question = "设计一个 8 位同步计数器。"
        contract = parse_task(question)
        agent_prompt = build_generation_prompt(contract, "Use nonblocking assignment.")
        self.assertGreater(len(agent_prompt), len(build_baseline_prompt(question)))
        self.assertIn("Use nonblocking assignment.", agent_prompt)


class MockFlowTests(unittest.TestCase):
    """Mock-flow tests use a workspace-local directory on purpose.

    tempfile.TemporaryDirectory creates a directory whose inherited
    permissions are not writable under every sandbox, which would make these
    tests report an environment restriction as a product defect.
    """

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1] / "experiments" / "runs" / "_unittest_mock_flow"
        self.addCleanup(shutil.rmtree, self.root, True)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "demo.v").write_text("module demo; endmodule\n", encoding="utf-8")
        (self.root / "demo_tb.v").write_text("module demo_tb; endmodule\n", encoding="utf-8")

    def test_mock_flow_writes_result(self) -> None:
        run_dir = self.root / "run"
        result = run_vivado_flow(
            self.root, self.root / "demo.v", self.root / "demo_tb.v", "demo_tb", "demo", run_dir, None, True
        )
        self.assertTrue(result["synthesis_pass"])
        self.assertTrue(synthesis_credit(result))
        self.assertTrue(result["synthesis_attempted"])
        stored = json.loads((run_dir / "flow_result.json").read_text(encoding="utf-8"))
        self.assertTrue(stored["simulation_pass"])
        self.assertTrue(stored["elaborate_pass"])

    def test_mock_run_dir_is_created_when_absent(self) -> None:
        nested = self.root / "fresh" / "run"
        result = run_vivado_flow(
            self.root, self.root / "demo.v", self.root / "demo_tb.v", "demo_tb", "demo", nested, None, True
        )
        self.assertTrue(result["synthesis_pass"])
        self.assertTrue((nested / "flow_result.json").is_file())


if __name__ == "__main__":
    unittest.main()
