from __future__ import annotations

from .task_parser import TaskContract

# Error categories that a code change cannot fix: the toolchain itself failed,
# or the failure is a host configuration problem. Retrying would burn wall clock
# and could mutate correct code into incorrect code.
NON_REPAIRABLE = frozenset({"toolchain"})


def build_baseline_prompt(question: str) -> str:
    """Prompt for the gain baseline.

    The competition requires run_baseline.sh to use the same inference service
    and context configuration as run.sh while bypassing the agent and the skill
    package: the prompt carries the question and nothing else, there is a
    single generation, no retry and no tool call. Do not add RTL rules, a
    structured contract, or repair guidance here - that is what run.sh is for,
    and mixing them in would make the reported gain meaningless.
    """
    return question


def build_generation_prompt(contract: TaskContract, skill_text: str) -> str:
    return f"""Generate one synthesizable Verilog module for the following task.

Hardware contract:
{contract.to_dict()}

Task:
{contract.raw_text}

Rules:
{skill_text}

Return only one Verilog code block. Keep the requested top-level port names and widths unchanged.
"""


def build_repair_prompt(contract: TaskContract, current_code: str, error_type: str, log_text: str, skill_text: str) -> str:
    return f"""Repair the Verilog module below without changing its external interface.

Task:
{contract.raw_text}

Detected error category: {error_type}

Relevant tool feedback:
{log_text[-5000:]}

Current code:
```verilog
{current_code}
```

Applicable RTL rules:
{skill_text}

Return only the complete corrected Verilog module.
"""

