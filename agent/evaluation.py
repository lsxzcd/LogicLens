"""Batch evaluation over a problem set.

Turns a directory of tasks into the numbers the competition asks for: per-level
pass rates, pass@k, wall-clock cost, and the gain of the agent over the bare
baseline. Before this existed there was no way to produce a pass@1 or pass@5
figure at all, because nothing iterated a dataset.

Each task is a directory (or a single file) whose prompt text is fed to the
agent or the baseline; the testbench is resolved per task by
`agent.testbench.resolve_testbench`, so a team can attach the VerilogEval
harness by dropping sidecar testbenches next to the prompts.
"""

from __future__ import annotations

import csv
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from .baseline import run_baseline
from .controller import LogicLensAgent

RESULT_FIELDS = (
    "task_id",
    "mode",
    "sample",
    "success",
    "compile_pass",
    "elaborate_pass",
    "simulation_pass",
    "synthesis_attempted",
    "synthesis_pass",
    "timing_constraint_pass",
    "sim_crashed",
    "attempts",
    "elapsed_seconds",
    "error_type",
    "testbench_source",
    "testbench_behavior",
)


@dataclass
class Task:
    task_id: str
    question_path: Path
    testbench_path: Path | None = None


@dataclass
class EvalConfig:
    project_root: Path
    mode: str = "agent"
    samples: int = 1
    max_attempts: int = 3
    vivado: str | None = None
    mock: bool = False
    testbench_mode: str = "auto"
    runs_dir: Path | None = None
    seed: int = 0
    limit: int | None = None
    extra: dict = field(default_factory=dict)


def discover_tasks(dataset_dir: Path) -> list[Task]:
    """Collect tasks from a dataset directory.

    A task is any `.txt`/`.md` prompt, or any directory that contains exactly
    one such prompt. A `<prompt>.tb.v` sidecar beside the prompt is attached
    automatically by the testbench resolver, so it is not listed here.
    """
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"dataset directory not found: {dataset_dir}")

    prompts: list[Path] = []
    for pattern in ("*.txt", "*.md"):
        prompts.extend(sorted(dataset_dir.rglob(pattern)))
    prompts = [p for p in prompts if not p.name.endswith(".tb.txt")]

    tasks: list[Task] = []
    for path in prompts:
        relative = path.relative_to(dataset_dir)
        task_id = str(relative.with_suffix("")).replace("\\", "/")
        tasks.append(Task(task_id=task_id, question_path=path))
    if not tasks:
        raise FileNotFoundError(f"no task prompts found under {dataset_dir}")
    return tasks


def _run_once(config: EvalConfig, task: Task, sample: int) -> dict:
    parent = config.runs_dir or (config.project_root / "experiments" / "runs")
    run_dir = parent / "eval" / f"{task.task_id.replace('/', '__')}__s{sample}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if config.mode == "baseline":
        result = run_baseline(
            project_root=config.project_root,
            question_path=task.question_path,
            vivado=config.vivado,
            mock=config.mock,
            run_dir=run_dir,
            testbench=task.testbench_path,
            testbench_mode=config.testbench_mode,
        )
    else:
        agent = LogicLensAgent(
            project_root=config.project_root,
            vivado=config.vivado,
            mock=config.mock,
            max_attempts=config.max_attempts,
            testbench=task.testbench_path,
            testbench_mode=config.testbench_mode,
        )
        result = agent.run(task.question_path, run_dir=run_dir, source="agent")
    return result


def _row(task: Task, mode: str, sample: int, result: dict) -> dict:
    history = result.get("history") or []
    last_error = next((h.get("error_type") for h in reversed(history) if h.get("error_type") not in (None, "none")), "")
    testbench = result.get("testbench") or {}
    return {
        "task_id": task.task_id,
        "mode": mode,
        "sample": sample,
        "success": int(bool(result.get("success"))),
        "compile_pass": int(bool(result.get("compile_pass"))),
        "elaborate_pass": int(bool(result.get("elaborate_pass"))),
        "simulation_pass": int(bool(result.get("simulation_pass"))),
        "synthesis_attempted": int(bool(result.get("synthesis_attempted"))),
        "synthesis_pass": int(bool(result.get("synthesis_pass"))),
        "timing_constraint_pass": int(bool(result.get("timing_constraint_pass"))),
        "sim_crashed": int(bool(result.get("sim_crashed"))),
        "attempts": result.get("best_attempt") or len(history),
        "elapsed_seconds": result.get("elapsed_seconds", 0.0),
        "error_type": last_error,
        "testbench_source": testbench.get("source", ""),
        "testbench_behavior": testbench.get("behavior", ""),
    }


def pass_at_k(successes: list[bool], k: int, samples: int) -> float:
    """Unbiased pass@k over `samples` independent attempts per task.

    `successes` is one task's per-sample outcomes. With c successes out of n
    samples, pass@k is 1 - C(n-c, k) / C(n, k); when fewer than k samples exist
    the best available prefix is used.
    """
    n = len(successes)
    if n == 0:
        return 0.0
    c = sum(1 for item in successes if item)
    k = min(k, n)
    if c == 0:
        return 0.0
    if n - c < k:
        return 1.0
    # Compute the combinatorial ratio multiplicatively to avoid huge integers.
    ratio = 1.0
    for index in range(k):
        ratio *= (n - c - index) / (n - index)
    return 1.0 - ratio


def summarize(rows: list[dict], samples: int) -> dict:
    by_task: dict[str, list[dict]] = {}
    for row in rows:
        by_task.setdefault(row["task_id"], []).append(row)

    tasks = len(by_task)
    per_stage = {
        stage: (sum(row[stage] for row in rows) / len(rows) if rows else 0.0)
        for stage in ("compile_pass", "elaborate_pass", "simulation_pass", "synthesis_pass")
    }
    summary = {
        "tasks": tasks,
        "runs": len(rows),
        "samples": samples,
        "compile_pass_rate": round(per_stage["compile_pass"], 4),
        "elaborate_pass_rate": round(per_stage["elaborate_pass"], 4),
        "simulation_pass_rate": round(per_stage["simulation_pass"], 4),
        "synthesis_pass_rate": round(per_stage["synthesis_pass"], 4),
        "success_rate": round(sum(row["success"] for row in rows) / len(rows), 4) if rows else 0.0,
        "task_success_rate": round(
            sum(1 for outcomes in by_task.values() if any(r["success"] for r in outcomes)) / tasks, 4
        )
        if tasks
        else 0.0,
        "sim_crash_runs": sum(row["sim_crashed"] for row in rows),
        "synthesis_skipped_runs": sum(1 for row in rows if not row["synthesis_attempted"]),
        "total_elapsed_seconds": round(sum(row["elapsed_seconds"] for row in rows), 1),
        "mean_elapsed_seconds": round(sum(row["elapsed_seconds"] for row in rows) / len(rows), 2) if rows else 0.0,
        "error_types": {},
    }
    for k in range(1, samples + 1):
        values = [pass_at_k([bool(r["success"]) for r in outcomes], k, samples) for outcomes in by_task.values()]
        summary[f"pass@{k}"] = round(sum(values) / len(values), 4) if values else 0.0
    for row in rows:
        if row["error_type"]:
            summary["error_types"][row["error_type"]] = summary["error_types"].get(row["error_type"], 0) + 1
    return summary


def run_evaluation(config: EvalConfig, dataset_dir: Path, output_dir: Path | None = None) -> dict:
    tasks = discover_tasks(dataset_dir)
    if config.limit is not None:
        tasks = tasks[: config.limit]

    # Shuffle so a partial run is not biased toward the start of the dataset.
    ordering = list(range(len(tasks)))
    random.Random(config.seed).shuffle(ordering)
    tasks = [tasks[index] for index in ordering]

    output_dir = output_dir or (config.project_root / "experiments" / "results" / f"{config.mode}_{int(time.time())}")
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for task in tasks:
        for sample in range(1, config.samples + 1):
            try:
                result = _run_once(config, task, sample)
            except Exception as exc:  # a single task must not abort the batch
                result = {
                    "success": False,
                    "compile_pass": False,
                    "elaborate_pass": False,
                    "simulation_pass": False,
                    "synthesis_attempted": False,
                    "synthesis_pass": False,
                    "timing_constraint_pass": False,
                    "sim_crashed": False,
                    "elapsed_seconds": 0.0,
                    "history": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            row = _row(task, config.mode, sample, result)
            rows.append(row)
            print(
                f"[{config.mode}] {task.task_id} s{sample}: "
                f"success={row['success']} sim={row['simulation_pass']} synth={row['synthesis_pass']} "
                f"{row['elapsed_seconds']}s tb={row['testbench_source']}"
            )

    csv_path = output_dir / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summary = summarize(rows, config.samples)
    summary["mode"] = config.mode
    summary["dataset"] = str(dataset_dir)
    summary["samples"] = config.samples
    summary["max_attempts"] = config.max_attempts
    summary["mock"] = config.mock
    summary["testbench_mode"] = config.testbench_mode
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "status.json").write_text(
        json.dumps({"completed": True, "mode": config.mode, "runs": len(rows)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary["output_dir"] = str(output_dir)
    summary["csv"] = str(csv_path)
    return summary


def render_gain_table(baseline: dict, agent: dict) -> str:
    """Markdown comparison for the design report."""
    lines = [
        "| 方案 | 可编译 | 仿真通过 | 可综合 | pass@1 | pass@k | 单题均耗时(s) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, summary in (("Baseline", baseline), ("LogicLens", agent)):
        top_k = max((int(key.split("@")[1]) for key in summary if key.startswith("pass@")), default=1)
        lines.append(
            f"| {label} | {summary.get('compile_pass_rate', 0):.3f} | {summary.get('simulation_pass_rate', 0):.3f} "
            f"| {summary.get('synthesis_pass_rate', 0):.3f} | {summary.get('pass@1', 0):.3f} "
            f"| {summary.get(f'pass@{top_k}', 0):.3f} | {summary.get('mean_elapsed_seconds', 0):.1f} |"
        )
    delta = agent.get("pass@1", 0.0) - baseline.get("pass@1", 0.0)
    lines += ["", f"pass@1 增益：**{delta:+.3f}**（相对同模型裸跑基线）"]
    return "\n".join(lines)
