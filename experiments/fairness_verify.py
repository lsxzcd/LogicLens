"""Check that the agent and the baseline ran the same model configuration.

The competition scores the gain of the agent over a single-shot baseline, and
that number is only meaningful if both sides used the same inference service and
sampling settings. A mismatch is silent: both runs succeed, both produce
plausible numbers, and the gain is simply wrong. This makes the check explicit.

    py -3 experiments/fairness_verify.py [--model-url URL] [--model NAME]

Uses one task and both entry points. The agent side runs against a local stub
model server so no real model is needed; what is being verified is that the two
code paths carry and record the same configuration, not the quality of any
particular model.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from agent.cli import COMPARABLE_KEYS, compare_configurations  # noqa: E402
from agent.model_client import ModelClient  # noqa: E402

QUESTION = ROOT / "experiments" / "data" / "verilogeval" / "examples" / "Prob001_zero_prompt.txt"
RUN_ROOT = ROOT / "experiments" / "runs" / "_fairness"
PORT = 8801

failures = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global failures
    mark = "OK  " if condition else "FAIL"
    print(f"[{mark}] {label}")
    if detail:
        print(f"        {detail}")
    if not condition:
        failures += 1


def run_pair(client: ModelClient, port: int) -> tuple[dict, dict]:
    from agent.baseline import run_baseline
    from agent.controller import LogicLensAgent
    import stub_model_server

    if RUN_ROOT.exists():
        shutil.rmtree(RUN_ROOT, ignore_errors=True)

    # A stub stands in for the model. The baseline deliberately has no mock mode -
    # it must exercise the real generation path - so a reachable endpoint is
    # needed for both sides. What is under test is the configuration plumbing.
    server, _ = stub_model_server.serve(port)
    try:
        baseline = run_baseline(
            project_root=ROOT,
            question_path=QUESTION,
            vivado=None,
            mock=False,
            run_dir=RUN_ROOT / "baseline",
            model_client=client,
        )
        # The agent takes the same client, so its recorded configuration comes
        # from the object the baseline used.
        agent = LogicLensAgent(project_root=ROOT, vivado=None, mock=True, model_client=client)
        agent_result = agent.run(QUESTION, run_dir=RUN_ROOT / "agent", source="fairness")
    finally:
        server.shutdown()
        server.server_close()
    return baseline, agent_result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-url", default=None, help="Defaults to the local stub server")
    parser.add_argument("--model", default="fairness-probe")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    if not QUESTION.is_file():
        print(f"fixture missing: {QUESTION}")
        return 2

    client = ModelClient(
        url=args.model_url or f"http://127.0.0.1:{args.port}/v1",
        model=args.model,
        seed=args.seed,
        temperature=0.33,
        top_p=0.77,
        max_tokens=512,
    )

    print("=== both sides record the configuration they used ===")
    baseline, agent = run_pair(client, args.port)

    check("baseline records a model configuration", bool(baseline.get("model")), json.dumps(baseline.get("model", {}), ensure_ascii=False))
    check("agent records a model configuration", bool(agent.get("model")), json.dumps(agent.get("model", {}), ensure_ascii=False))
    check("baseline records elapsed_seconds", "elapsed_seconds" in baseline, f"elapsed={baseline.get('elapsed_seconds')}")

    print("\n=== the two configurations agree ===")
    differences = compare_configurations(agent.get("model", {}), baseline.get("model", {}))
    check("no configuration differences", not differences, "; ".join(differences) if differences else "all comparable keys equal")

    print("\n=== command-line values actually reach both sides ===")
    for key, expected in (("model", args.model), ("seed", args.seed), ("temperature", 0.33), ("top_p", 0.77), ("max_tokens", 512)):
        for label, result in (("baseline", baseline), ("agent", agent)):
            actual = (result.get("model") or {}).get(key)
            check(f"{label} {key} == {expected!r}", actual == expected, f"recorded {actual!r}")

    print("\n=== the comparison detects a real mismatch ===")
    # A check that cannot fail is worthless, so a deliberate mismatch is injected.
    tampered = dict(agent.get("model", {}))
    tampered["temperature"] = 0.99
    detected = compare_configurations(tampered, baseline.get("model", {}))
    check("a differing temperature is reported", any("temperature" in item for item in detected), "; ".join(detected))

    tampered_model = dict(agent.get("model", {}))
    tampered_model["model"] = "a-different-model"
    detected_model = compare_configurations(tampered_model, baseline.get("model", {}))
    check("a differing model name is reported", any("model" in item for item in detected_model), "; ".join(detected_model))

    print("\n=== the shared keys cover what matters ===")
    for key in ("endpoint", "model", "temperature", "top_p", "max_tokens", "seed"):
        check(f"{key} is compared", key in COMPARABLE_KEYS)

    print(f"\n===== {failures} failed check(s) =====")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
