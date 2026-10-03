from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.baseline import run_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a single-shot RTL generation baseline")
    parser.add_argument("--question", required=True)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--vivado", default=None)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--testbench", default=None, help="Explicit testbench file to verify against")
    parser.add_argument(
        "--testbench-mode",
        choices=("auto", "sidecar", "generated"),
        default="auto",
        help="How to obtain a testbench: explicit/sidecar file, or generate one",
    )
    args = parser.parse_args()

    result = run_baseline(
        project_root=Path(__file__).resolve().parent,
        question_path=Path(args.question).resolve(),
        vivado=args.vivado,
        mock=args.mock,
        run_dir=Path(args.run_dir).resolve() if args.run_dir else None,
        testbench=Path(args.testbench).resolve() if args.testbench else None,
        testbench_mode=args.testbench_mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

