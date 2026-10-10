"""Model arguments shared by the agent and the baseline entry points.

These live in one place on purpose. The competition measures the agent's gain
over the single-shot baseline and requires both to use the same inference
service and context configuration. If the two entry points defined the options
separately they would drift, and a run could be pinned to a model on one side
while the other silently used a default - which would make the headline gain
number meaningless. Anything that changes the model configuration belongs here.
"""

from __future__ import annotations

import argparse

from .model_client import ModelClient

GROUP_TITLE = "model (defaults come from LOGICLENS_* environment variables)"


def add_model_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group(GROUP_TITLE)
    group.add_argument("--model-url", default=None, help="Base URL or full chat-completions URL")
    group.add_argument("--model", default=None, help="Model name to request")
    group.add_argument("--api-key", default=None)
    group.add_argument("--temperature", type=float, default=None)
    group.add_argument("--top-p", type=float, default=None)
    group.add_argument("--max-tokens", type=int, default=None)
    group.add_argument("--seed", type=int, default=None, help="Set for a reproducible run")
    group.add_argument("--model-timeout", type=int, default=None, help="Per-request timeout in seconds")


def client_from_args(args: argparse.Namespace) -> ModelClient:
    """Build the client from parsed arguments, falling back to the environment."""
    return ModelClient(
        url=getattr(args, "model_url", None),
        model=getattr(args, "model", None),
        api_key=getattr(args, "api_key", None),
        timeout=getattr(args, "model_timeout", None),
        temperature=getattr(args, "temperature", None),
        top_p=getattr(args, "top_p", None),
        max_tokens=getattr(args, "max_tokens", None),
        seed=getattr(args, "seed", None),
    )


# The keys that must match between the agent and the baseline for a gain
# comparison to be valid. Kept here so tests and the fairness checker agree on
# one definition instead of each carrying its own list.
COMPARABLE_KEYS = (
    "endpoint",
    "model",
    "temperature",
    "top_p",
    "max_tokens",
    "seed",
)


def compare_configurations(agent: dict, baseline: dict) -> list[str]:
    """Return the configuration keys that differ between the two sides.

    An empty list means the comparison is fair with respect to the model
    configuration. Parameters that legitimately differ between the two runs -
    the retry count, and therefore nothing that affects a single generation -
    are deliberately not compared.
    """
    differences = []
    for key in COMPARABLE_KEYS:
        left = (agent or {}).get(key)
        right = (baseline or {}).get(key)
        if left != right:
            differences.append(f"{key}: agent={left!r} baseline={right!r}")
    return differences
