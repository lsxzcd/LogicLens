from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.controller import LogicLensAgent
from agent.model_client import ModelClient


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
    model = parser.add_argument_group("model (defaults come from LOGICLENS_* environment variables)")
    model.add_argument("--model-url", default=None, help="Base URL or full chat-completions URL")
    model.add_argument("--model", default=None, help="Model name to request")
    model.add_argument("--api-key", default=None)
    model.add_argument("--temperature", type=float, default=None)
    model.add_argument("--top-p", type=float, default=None)
    model.add_argument("--max-tokens", type=int, default=None)
    model.add_argument("--seed", type=int, default=None, help="Set for a reproducible run")
    model.add_argument("--model-timeout", type=int, default=None, help="Per-request timeout in seconds")
    args = parser.parse_args()

    question_path = Path(args.question).resolve()
    if not question_path.is_file():
        parser.error(f"question file not found: {question_path}")

    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    client = ModelClient(
        url=args.model_url,
        model=args.model,
        api_key=args.api_key,
        timeout=args.model_timeout,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
        seed=args.seed,
    )
    agent = LogicLensAgent(
        project_root=Path(__file__).resolve().parent,
        vivado=args.vivado,
        mock=args.mock,
        max_attempts=args.max_attempts,
        testbench=Path(args.testbench).resolve() if args.testbench else None,
        testbench_mode=args.testbench_mode,
        model_client=client,
    )
    result = agent.run(question_path, run_dir=run_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())

