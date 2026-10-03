from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    dataset = Path(args.dataset).resolve()
    out_root = Path(args.out).resolve() if args.out else None
    runs_dir = Path(args.runs_dir).resolve() if args.runs_dir else None

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
