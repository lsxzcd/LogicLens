from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.cli import add_model_arguments, client_from_args, compare_configurations
from agent.evaluation import EvalConfig, render_gain_table, run_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a batch RTL evaluation and report pass@k")
    parser.add_argument("--dataset", required=True, help="Directory of task prompts (e.g. a VerilogEval export)")
    parser.add_argument("--mode", choices=("agent", "baseline", "both"), default="both")
    parser.add_argument("--samples", type=int, default=1, help="Independent attempts per task (5 gives pass@5)")
    parser.add_argument("--max-attempts", type=int, default=3, help="Repair attempts per sample in agent mode")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N tasks (smoke runs)")
    parser.add_argument("--seed", type=int, default=0, help="Shuffle seed for task ordering")
    parser.add_argument("--vivado", default=None)
    parser.add_argument("--mock", action="store_true", help="Software-only check; never report these numbers")
    parser.add_argument(
        "--testbench-mode",
        choices=("auto", "sidecar", "generated"),
        default="auto",
        help="How to obtain a testbench per task",
    )
    parser.add_argument("--out", default=None, help="Output directory for results.csv and summary.json")
    parser.add_argument("--runs-dir", default=None, help="Where per-run artifacts are written")
    # Shared with run.py and run_baseline.py, so a batch run cannot end up with
    # the two sides configured differently.
    add_model_arguments(parser)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    dataset = Path(args.dataset).resolve()
    out_root = Path(args.out).resolve() if args.out else None
    runs_dir = Path(args.runs_dir).resolve() if args.runs_dir else None

    # ONE client for the whole run, shared by both modes. Building a client per
    # mode would let the baseline and the agent run different models without
    # anything saying so, and the gain would then be meaningless.
    client = client_from_args(args)

    def build(mode: str) -> EvalConfig:
        return EvalConfig(
            project_root=root,
            mode=mode,
            samples=max(1, args.samples),
            max_attempts=max(1, args.max_attempts),
            vivado=args.vivado,
            mock=args.mock,
            testbench_mode=args.testbench_mode,
            runs_dir=runs_dir,
            seed=args.seed,
            limit=args.limit,
            model_client=client,
        )

    summaries: dict[str, dict] = {}
    modes = ("baseline", "agent") if args.mode == "both" else (args.mode,)
    for mode in modes:
        target = (out_root / mode) if out_root else None
        summaries[mode] = run_evaluation(build(mode), dataset, target)

    for mode, summary in summaries.items():
        print(f"\n===== {mode} =====")
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    if "baseline" in summaries and "agent" in summaries:
        # The gain only means something if both sides ran the same model with the
        # same sampling settings, so a mismatch is reported here rather than left
        # for a reader to spot in the summaries.
        differences = compare_configurations(
            summaries["agent"].get("model_configuration", {}),
            summaries["baseline"].get("model_configuration", {}),
        )
        if differences:
            print("\n" + "!" * 72)
            print("警告：基线与智能体的模型配置不一致，增益数据不可信：")
            for line in differences:
                print(f"  - {line}")
            print("!" * 72)
        else:
            print("\n模型配置一致性检查：基线与智能体一致")

        table = render_gain_table(summaries["baseline"], summaries["agent"])
        print("\n" + table)
        destination = (out_root or Path(summaries["agent"]["output_dir"]).parent) / "gain.md"
        destination.write_text(table + "\n", encoding="utf-8")
        print(f"\n增益表已写入 {destination}")

    if args.mock:
        print("\n警告：--mock 结果仅供软件流程自检，禁止写入正式实验结论。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
