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
from .model_client import ModelClient

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
    # Attempt bookkeeping, stated separately because the kept candidate and the
    # last round are different facts.
    "best_attempt",
    "attempt_count",
    "best_error",
    "last_error",
    "attempts",
    "elapsed_seconds",
    "wall_clock_seconds",
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
    # One client instance is built here and handed to both the agent and the
    # baseline. Letting each side construct its own would let them run different
    # models or sampling settings without anything reporting it, and the gain
    # comparison would then be meaningless.
    model_client: ModelClient | None = None
    extra: dict = field(default_factory=dict)

    def client(self) -> ModelClient:
        if self.model_client is None:
            self.model_client = ModelClient()
        return self.model_client


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
            # The same client instance the agent side uses.
            model_client=config.client(),
        )
    else:
        agent = LogicLensAgent(
            project_root=config.project_root,
            vivado=config.vivado,
            mock=config.mock,
            max_attempts=config.max_attempts,
            testbench=task.testbench_path,
            testbench_mode=config.testbench_mode,
            model_client=config.client(),
        )
        result = agent.run(task.question_path, run_dir=run_dir, source="agent")
    return result


def _row(task: Task, mode: str, sample: int, result: dict) -> dict:
    """One CSV row, with the attempt bookkeeping stated honestly.

    A previous version had a single column spelled `attempts` whose value was
    actually `best_attempt`, and an `error_type` taken from the last attempt that
    reported an error rather than from the attempt that was selected. A teammate
    reviewing the lab logs caught both: the best candidate can come from an early
    round, so its error type and the last round's error are different facts, and a
    column named `attempts` that holds a round number invites the reader to
    conclude the repair loop only ran once. The columns are now:

    * `best_attempt` - which round produced the candidate that was kept;
    * `attempt_count` - how many rounds actually ran;
    * `best_error` - the error type of the kept candidate (empty when it passed);
    * `last_error` - the error type of the final round;
    * `attempts` - retained as an alias of `best_attempt` for older summaries.
    """
    history = result.get("history") or []
    best_attempt = result.get("best_attempt")
    if not best_attempt and history:
        # A result written before this field existed: fall back to the last round.
        best_attempt = history[-1].get("attempt")

    best_error = ""
    for record in history:
        if record.get("attempt") == best_attempt:
            best_error = record.get("error_type") or ""
            break

    last_error = ""
    if history:
        last_error = history[-1].get("error_type") or ""

    attempted = len(history)
    best_round = best_attempt or attempted
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
        "best_attempt": best_round,
        "attempt_count": attempted,
        "best_error": best_error,
        "last_error": last_error,
        # Kept so an older summary or downstream reader still resolves.
        "attempts": best_round,
        # The tool time of the kept attempt. Model calls are outside it.
        "elapsed_seconds": result.get("elapsed_seconds", 0.0),
        # The whole task, model calls included. Quote this as wall clock.
        "wall_clock_seconds": result.get("wall_clock_seconds", result.get("elapsed_seconds", 0.0)),
        "error_type": best_error or last_error,
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
        stage: (sum(row.get(stage, 0) for row in rows) / len(rows) if rows else 0.0)
        for stage in ("compile_pass", "elaborate_pass", "simulation_pass", "synthesis_pass")
    }

    def total(key: str) -> float:
        return sum(row.get(key, row.get("elapsed_seconds", 0.0)) for row in rows)

    summary = {
        "tasks": tasks,
        "runs": len(rows),
        "samples": samples,
        "compile_pass_rate": round(per_stage["compile_pass"], 4),
        "elaborate_pass_rate": round(per_stage["elaborate_pass"], 4),
        "simulation_pass_rate": round(per_stage["simulation_pass"], 4),
        "synthesis_pass_rate": round(per_stage["synthesis_pass"], 4),
        "success_rate": round(sum(row.get("success", 0) for row in rows) / len(rows), 4) if rows else 0.0,
        "task_success_rate": round(
            sum(1 for outcomes in by_task.values() if any(r.get("success") for r in outcomes)) / tasks, 4
        )
        if tasks
        else 0.0,
        "sim_crash_runs": sum(row.get("sim_crashed", 0) for row in rows),
        "synthesis_skipped_runs": sum(1 for row in rows if not row.get("synthesis_attempted")),
        # Tool time only: the sum of the verification flows that were run. It
        # excludes model generation, so it is not the experiment's duration.
        "total_tool_seconds": round(total("elapsed_seconds"), 1),
        "mean_tool_seconds": round(total("elapsed_seconds") / len(rows), 2) if rows else 0.0,
        # The whole run, model calls included. This is the figure to quote.
        "total_wall_clock_seconds": round(total("wall_clock_seconds"), 1),
        "mean_wall_clock_seconds": round(total("wall_clock_seconds") / len(rows), 2) if rows else 0.0,
        "attempt_counts": {},
        "error_types": {},
        "best_error_types": {},
    }
    # `elapsed_seconds` used to be reported as the experiment's duration when it
    # was only the tool time. Kept as an alias so an older reader still resolves,
    # but the honest fields above are what a report should quote.
    summary["total_elapsed_seconds"] = summary["total_tool_seconds"]
    summary["mean_elapsed_seconds"] = summary["mean_tool_seconds"]
    for k in range(1, samples + 1):
        values = [
            pass_at_k([bool(r.get("success")) for r in outcomes], k, samples) for outcomes in by_task.values()
        ]
        summary[f"pass@{k}"] = round(sum(values) / len(values), 4) if values else 0.0
    for row in rows:
        count = row.get("attempt_count", 0)
        summary["attempt_counts"][str(count)] = summary["attempt_counts"].get(str(count), 0) + 1
        kind = row.get("error_type") or ""
        if kind:
            summary["error_types"][kind] = summary["error_types"].get(kind, 0) + 1
        # Recorded separately because the kept candidate and the final round can
        # carry different errors: a repair may fix one problem and introduce
        # another, and only the kept candidate's error describes the outcome.
        best = row.get("best_error") or ""
        if best:
            summary["best_error_types"][best] = summary["best_error_types"].get(best, 0) + 1
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
    # Recorded so the baseline and agent summaries can be compared mechanically.
    # A gain figure is only meaningful when these agree.
    summary["model_configuration"] = config.client().describe()
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
