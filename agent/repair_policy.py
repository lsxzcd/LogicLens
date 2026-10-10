from __future__ import annotations

from .task_parser import TaskContract

# Error categories that a code change cannot fix: the toolchain itself failed,
# or the failure is a host configuration problem. Retrying would burn wall clock
# and could mutate correct code into incorrect code.
NON_REPAIRABLE = frozenset({"toolchain"})

# Rules that address the most common failures observed with a small local model.
# Two behaviours were measured repeatedly: it invents a clock and a reset for
# tasks whose interface has neither, and - after being told not to declare them -
# it still writes `always @(posedge clk)` and references the now-missing `clk`,
# which fails to compile. A 1.5B-class model follows a concrete skeleton far more
# reliably than an abstract rule, so both are given, and the skeletons appear
# before the task text.
_INTERFACE_RULES = """\
The module interface is FIXED. Declare EXACTLY the ports listed above, and no others.
- Never add a clock, a reset, an enable, or any other port that is not listed.
- Port names, directions and widths must match the list character for character.
- Every signal you read or assign must either be a port from the list OR be
  declared as `wire`/`reg` inside the module. An undeclared name is a compile error.

Choose exactly one skeleton below and copy its shape:

If the port list has NO clock port, the module is COMBINATIONAL. Use this shape,
referencing only listed ports and internal signals you declare yourself:
    <type> <port_name>;                       // declared ports
    wire <internal>;                           // any internal signal
    assign <port_name> = <expression>;         // or:  always @(*) begin ... end
  Do NOT write `posedge`, `negedge`, `<=`, or any clock/reset name.

If the port list HAS a clock port, the module is SEQUENTIAL. Use this shape:
    always @(posedge <the listed clock port>) begin
        ... // nonblocking assignments to declared `reg` outputs
    end"""


def render_port_list(contract: TaskContract) -> str:
    """Render the contract's interface as Verilog declarations.

    The model is given declarations rather than a dictionary dump: a small model
    copies a declaration faithfully but treats an abstract description as
    advisory, which is how extra clock and reset ports appeared in every
    combinational task.
    """
    if not contract.ports:
        return "(the task text below is the only interface description available)"
    lines = []
    for port in contract.ports:
        width = f" {port.width_range()}" if port.width_range() else ""
        lines.append(f"  {port.direction} wire{width} {port.name}")
    return "\n".join(lines)


def describe_sequential(contract: TaskContract) -> str:
    """One line stating whether the interface implies sequential or combinational logic."""
    if any(port.name == contract.clock_spec.name for port in contract.ports):
        reset = contract.reset_spec
        if any(port.name == reset.name for port in contract.ports):
            return (
                f"This module is SEQUENTIAL. Use `always @(posedge {contract.clock_spec.name})`. "
                f"The reset port is `{reset.name}`, active {reset.polarity}, {reset.style}."
            )
        return f"This module is SEQUENTIAL. Use `always @(posedge {contract.clock_spec.name})`. There is no reset port."
    return (
        "This module is COMBINATIONAL: it has no clock port. "
        "Use `assign` or `always @(*)`. Do not use posedge/negedge or a reset."
    )


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
    return f"""Write one synthesizable Verilog module for the task below.

Module name: {contract.top_module}

Required ports (exactly these, in any order):
{render_port_list(contract)}

{_INTERFACE_RULES}

{describe_sequential(contract)}

Task:
{contract.raw_text}

Additional RTL rules:
{skill_text}

Return only the Verilog module, with no explanation and no markdown fences.
"""


def build_repair_prompt(
    contract: TaskContract,
    current_code: str,
    error_type: str,
    log_text: str,
    skill_text: str,
    lint_findings: str = "",
) -> str:
    """Build a repair prompt that does not show the failing code.

    Measured behaviour of a small local model: when the broken module is quoted
    in the prompt, the model reproduces that module's structure verbatim - it
    kept emitting `always @(posedge clk)` for a combinational task across every
    attempt, ignoring both the error message and a changed seed. Withholding the
    code and giving only the interface constraints plus a short error summary
    removed that failure entirely (0/3 outputs contained posedge/negedge, versus
    3/3 when the code was shown).

    `lint_findings` carries defects detected structurally before simulation. A
    concrete, named defect is far more actionable for a small model than a
    simulation mismatch count.
    """
    summary = _summarise_log(log_text)
    structural = ""
    if lint_findings:
        structural = (
            "\nStatic checks found these concrete defects in the failed attempt:\n"
            f"{lint_findings}\n"
        )
    return f"""Write one synthesizable Verilog module for the task below.
A previous attempt failed verification; produce a fresh, corrected module.

Module name: {contract.top_module}

Required ports (exactly these, in any order):
{render_port_list(contract)}

{_INTERFACE_RULES}

{describe_sequential(contract)}

Task:
{contract.raw_text}
{structural}
What went wrong last time (error category: {error_type}):
{summary}

Additional RTL rules:
{skill_text}

Write the complete corrected module from scratch. Do not reuse the structure of
the failed attempt. Return only the Verilog module, with no explanation and no
markdown fences.
"""


def _summarise_log(log_text: str, limit: int = 12) -> str:
    """Extract the actionable error lines from a tool log.

    Only error and fatal lines are kept. A full log's informational output and
    warnings dilute the signal, and the model treats a short list of concrete
    errors far more reliably than a wall of text.
    """
    interesting = []
    for line in (log_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if "ERROR" in upper or "FATAL" in upper or "$FATAL" in upper:
            interesting.append(stripped)
        if len(interesting) >= limit:
            break
    if not interesting:
        return "(no error line was captured; the tool output was empty)"
    return "\n".join(interesting)
