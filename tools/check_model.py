"""Check that the configured model endpoint is reachable and usable.

Run this before any evaluation: a wrong path or an unloaded model otherwise
surfaces as a failed run rather than as a configuration message.

    py -3 tools/check_model.py
    py -3 tools/check_model.py --model-url http://127.0.0.1:8000/v1 --model Qwen2.5-Coder-7B
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.model_client import ModelClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the configured model endpoint")
    parser.add_argument("--model-url", default=None, help="Base URL or full chat-completions URL")
    parser.add_argument("--model", default=None, help="Model name to request")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()

    client = ModelClient(
        url=args.model_url,
        model=args.model,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    report = client.probe()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("model endpoint check")
        for key in ("endpoint", "model", "temperature", "top_p", "max_tokens", "seed", "timeout_seconds"):
            print(f"  {key:18}: {report.get(key)}")
        print()
        if report.get("ok"):
            print(f"  OK  replied in {report['elapsed_seconds']}s ({report['reply_chars']} chars)")
            print(f"      preview: {report.get('reply_preview')!r}")
        else:
            print(f"  FAILED: {report.get('error')}")
            print()
            print("Things to check, in order:")
            print("  1. the inference server is running and the model is loaded")
            print("  2. the URL ends at /v1 (the chat path is appended automatically)")
            print("  3. the model name matches what the server reports")
            print("  4. for a gated or proxied host, set LOGICLENS_API_KEY")
            print("  5. raise LOGICLENS_TIMEOUT if the first token is slow (model load)")

    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
