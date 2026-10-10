from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.cli import add_model_arguments, client_from_args
from agent.controller import LogicLensAgent


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LogicLens RTL repair agent")
    parser.add_argument("--question", required=True, help="Path to a natural-language RTL task")
    parser.add_argument("--mock", action="store_true", help="Use the bundled answer and mock verification")
    parser.add_argument("--vivado", default=None, help="Path to vivado or vivado.bat")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--run-dir", default=None, help="Directory for generated artifacts")
    parser.add_argument("--testbench", default=None, help="Explicit testbench file to verify against")
    parser.add_argument(
        "--testbench-mode",
        choices=("auto", "sidecar", "generated"),
        default="auto",
        help="How to obtain a testbench: explicit/sidecar file, or generate one",
    )
    # Shared with run_baseline.py: the gain comparison requires both sides to use
    # the same inference service and sampling configuration.
    add_model_arguments(parser)
    args = parser.parse_args()

    question_path = Path(args.question).resolve()
    if not question_path.is_file():
        parser.error(f"question file not found: {question_path}")

    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    agent = LogicLensAgent(
        project_root=Path(__file__).resolve().parent,
        vivado=args.vivado,
        mock=args.mock,
        max_attempts=args.max_attempts,
        testbench=Path(args.testbench).resolve() if args.testbench else None,
        testbench_mode=args.testbench_mode,
        model_client=client_from_args(args),
    )
    result = agent.run(question_path, run_dir=run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

