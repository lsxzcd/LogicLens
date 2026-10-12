"""Static checks for the structural mistakes a small model repeats.

These are deliberately mechanical and evidence-driven rather than a general
linter. Each rule encodes a failure that was actually observed while running the
VerilogEval suite against a 1.5B local model, and each is cheap enough to run
before spending a simulation on the candidate.

Measured examples this catches:

* `always @(posedge in)` in a task whose interface has no clock port - the model
  treated a data input as a clock edge, which simulates but never matches.
* an expression that is algebraically the input, such as
  `assign out = b3<<24 | b2<<16 | b1<<8 | b0;` where the `bN` are just slices of
  `in` in the same positions, i.e. a byte swap that swaps nothing.

Run from the agent as `lint(candidate, contract)`; findings are fed back into the
repair prompt so the next attempt has a concrete defect to fix instead of only a
simulation mismatch count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .task_parser import TaskContract

_CLOCKISH_NAMES = ("clk", "clock", "clk_i", "i_clk", "aclk")

_MODULE_RE = re.compile(
    r"\bmodule\s+(?P<name>[A-Za-z_]\w*)\s*(?:#\s*\([^)]*\)\s*)?\((?P<ports>[^;]*?)\)\s*;",
    re.S,
)
_PORT_RE = re.compile(
    r"\b(?P<dir>input|output|inout)\b\s*(?P<type>wire|reg|logic|bit)?\s*"
    r"(?P<width>\[[^\]]*\])?\s*(?P<name>[A-Za-z_]\w*)",
    re.I,
)
_EDGE_RE = re.compile(r"\b(?:pos|neg)edge\s+([A-Za-z_]\w*)", re.I)
_ASSIGN_RE = re.compile(r"\bassign\s+([A-Za-z_]\w*)\s*=\s*([^;]+);", re.S)


@dataclass
class Finding:
    rule: str
    message: str

    def render(self) -> str:
        return f"[{self.rule}] {self.message}"


def declared_ports(rtl: str) -> list[str]:
    match = _MODULE_RE.search(rtl)
    if not match:
        return []
    return [m.group("name") for m in _PORT_RE.finditer(match.group("ports"))]


def declared_signals(rtl: str) -> set[str]:
    """Names declared inside the module body (wire/reg/logic), plus ports."""
    names = set(declared_ports(rtl))
    for match in re.finditer(r"\b(?:wire|reg|logic|bit)\b\s*(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)", rtl):
        names.add(match.group(1))
    return names


def check_clock_edges(rtl: str, contract: TaskContract) -> list[Finding]:
    """Flag posedge/negedge on anything that is not the contract's clock port.

    A combinational task has no clock at all, so any edge sensitivity is wrong.
    A sequential task may only be sensitive to its own clock port; using a data
    input as an edge (observed: `always @(posedge in)`) silently produces a
    module that never behaves correctly.
    """
    findings: list[Finding] = []
    edges = _EDGE_RE.findall(rtl)
    if not edges:
        return findings

    port_names = declared_ports(rtl)
    expected_clock = contract.clock_spec.name
    contract_has_clock = any(name == expected_clock for name in port_names)

    if not contract_has_clock:
        findings.append(
            Finding(
                "combinational_uses_edge",
                "the interface has no clock port, so the module must not use "
                f"posedge/negedge, but it is sensitive to: {', '.join(sorted(set(edges)))}",
            )
        )
        return findings

    for signal in sorted(set(edges)):
        if signal != expected_clock:
            findings.append(
                Finding(
                    "edge_on_non_clock_signal",
                    f"`{signal}` is used as a clock edge but the clock port is "
                    f"`{expected_clock}`; a data input used as an edge never matches",
                )
            )
    return findings


def _slice_origins(rtl: str) -> dict[str, tuple[str, int, int]]:
    """Map a signal to (source, low_bit, high_bit) when it is a bit slice of another.

    Intermediate wires are common: the observed failure assigned
    `b0 = in[7:0]` .. `b3 = in[31:24]` and then combined the four names, so the
    identity is only visible after following the aliases.
    """
    origins: dict[str, tuple[str, int, int]] = {}
    for match in _ASSIGN_RE.finditer(rtl):
        target, expression = match.group(1), match.group(2).strip()
        inner = re.fullmatch(r"([A-Za-z_]\w*)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]", expression)
        if inner:
            origins[target] = (inner.group(1), int(inner.group(2)), int(inner.group(3)))
    return origins


def check_identity_expression(rtl: str, contract: TaskContract) -> list[Finding]:
    """Flag an output that reconstructs a source from shifted slices of itself.

    The observed failure was a byte swap written as
    `out = b3<<24 | b2<<16 | b1<<8 | b0` where `bN = in[...]` at that same
    position. Concatenating shifted slices in ascending order reproduces the
    source unchanged, so the design can never differ from its input.

    Aliases are resolved first, because the slices usually reach the output
    through intermediate wires rather than appearing inline.
    """
    findings: list[Finding] = []
    origins = _slice_origins(rtl)

    for match in _ASSIGN_RE.finditer(rtl):
        target, expression = match.group(1), match.group(2)
        if target in origins:
            continue
        terms = re.findall(
            r"([A-Za-z_]\w*)\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*(?:<<\s*(\d+))?",
            expression,
        )
        resolved: list[tuple[str, int, int]] = []
        for name, low, high, shift in terms:
            if name in ("b",) or not name:
                continue
            if name in origins:
                source, slice_low, slice_high = origins[name]
            elif low and high:
                source, slice_low, slice_high = name, int(low), int(high)
            else:
                continue
            resolved.append((source, min(slice_low, slice_high), int(shift or 0)))
        if len(resolved) < 2:
            continue
        sources = {source for source, _, _ in resolved}
        if len(sources) != 1:
            continue
        source = sources.pop()
        if source == target:
            continue
        # Identity when every slice sits at the same bit offset as its shift,
        # and the offsets are distinct.
        offsets = sorted((low, shift) for _, low, shift in resolved)
        if all(low == shift for low, shift in offsets) and len({low for low, _ in offsets}) == len(offsets):
            findings.append(
                Finding(
                    "identity_expression",
                    f"`{target}` is assembled from shifted slices of `{source}` whose shift "
                    "amounts equal their bit offsets, so it reproduces the source unchanged; "
                    "the intended reordering is missing",
                )
            )
    return findings


def check_undeclared_identifiers(rtl: str, contract: TaskContract) -> list[Finding]:
    """Flag an edge or procedural target that is neither a port nor declared.

    Observed: `always @(posedge clk)` in a module whose port list has no `clk`,
    after the model had been told not to add the port. That is a compile error
    (`'clk' is not declared`) which costs a whole round trip.
    """
    findings: list[Finding] = []
    known = declared_signals(rtl)
    for signal in sorted(set(_EDGE_RE.findall(rtl))):
        if signal not in known:
            findings.append(
                Finding(
                    "undeclared_clock_signal",
                    f"`{signal}` is used as a clock edge but is neither a port nor declared "
                    "inside the module, so the file will not compile",
                )
            )
    return findings


def lint(rtl: str, contract: TaskContract) -> list[Finding]:
    """Run every structural check and return the findings, most severe first."""
    findings: list[Finding] = []
    findings.extend(check_undeclared_identifiers(rtl, contract))
    findings.extend(check_clock_edges(rtl, contract))
    findings.extend(check_identity_expression(rtl, contract))
    return findings


# An always block whose sensitivity is entirely edge-based.
_EDGE_BLOCK_RE = re.compile(
    r"always\s*@\s*\(\s*(?P<sensitivity>(?:pos|neg)edge\s+[A-Za-z_]\w*\s*(?:or\s+(?:pos|neg)edge\s+[A-Za-z_]\w*\s*)*)\)"
    r"(?P<body>\s*(?:begin\b.*?end\b|(?:(?!\bend\b).)*;))",
    re.S | re.I,
)

_ALWAYS_RE = re.compile(r"always\s*@\s*\([^)]*\)\s*(?P<body>begin\b.*?\bend\b|(?:(?!\bbegin\b).)*?;)", re.S)
# An assignment to a simple name, taking the rightmost identifier before the
# operator. Branching on whether an identifier follows handles both operators
# without the lookbehind that was silently rejecting `<=`.
_PROCEDURAL_ASSIGN_RE = re.compile(
    r"(?:(?P<before>[A-Za-z_]\w*)\s*)?(?P<op><=|=)(?!=)\s*(?P<after>[A-Za-z_]\w*)?"
)


def _assigned_name(match: re.Match) -> str | None:
    """Which signal an assignment target names, or None if this is not one.

    `before` is the rightmost identifier before the operator, which is the target
    in `q <= d`, `out = a & b` and `sum_reg = x + y`. When there is no identifier
    before the operator it is a comparison inside an expression (`a == b`), so the
    token after it is not a target.
    """
    if match.group("before"):
        return match.group("before")
    return None


def _signals_assigned_in_always(rtl: str) -> set[str]:
    """Names that receive a procedural assignment inside an always block.

    In Verilog the left-hand side of a procedural assignment must be a variable,
    so anything in this set has to be declared `reg` (or `logic`), never `wire`.
    """
    names: set[str] = set()
    for block in _ALWAYS_RE.finditer(rtl):
        for match in _PROCEDURAL_ASSIGN_RE.finditer(block.group("body")):
            name = _assigned_name(match)
            if name:
                names.add(name)
    return names


def declare_procedural_outputs(rtl: str) -> str:
    """Turn `output wire x` into `output reg x` when x is assigned procedurally.

    Measured on the vector-reversal and mux tasks: the model declares
    `output wire out` and then drives it from an always block, which is a type
    error - `procedural assignment to a non-register out is not permitted`. It
    was the cause of every remaining `unknown` compile failure once the edge
    sensitivity had been dealt with.

    This is again a mechanical fact rather than a guess: a name assigned inside an
    always block must be a variable, so `wire` is simply the wrong keyword there.
    Only the keyword changes; the port name, direction, width and order are left
    exactly as written, and a port that is not assigned procedurally is untouched.
    """
    if not rtl:
        return rtl
    procedural = _signals_assigned_in_always(rtl)
    if not procedural:
        return rtl

    def fix(match: re.Match) -> str:
        name = match.group("name")
        if name not in procedural:
            return match.group(0)
        # Keep everything except the `wire` keyword, which becomes `reg`.
        return match.group("head") + "reg" + match.group("tail")

    port_pattern = re.compile(
        r"(?P<head>\boutput\b\s+)wire(?P<tail>\s*(?:\[[^\]]*\])?\s*(?P<name>[A-Za-z_]\w*))",
        re.I,
    )
    return port_pattern.sub(fix, rtl)


def rewrite_combinational(rtl: str, contract: TaskContract) -> str:
    """Repair the shapes that follow mechanically from the contract.

    This addresses the most common failures measured on the VerilogEval set with a
    small local model. Two shapes were observed, and both were reported correctly
    by the linter while the model reproduced them on every repair round:

    1. A purely combinational task answered with
       `always @(posedge a or posedge b)`. This was reported on 39 attempts.
    2. An output declared `wire` but driven from an always block, which does not
       compile. Fixing only (1) left ten `unknown` compile failures behind.

    Both are mechanical, not guesses. If the contract declares no clock port then
    the design is combinational by definition, and an edge sensitivity on a data
    input cannot be what the task wants; and a signal assigned inside an always
    block must be a variable, so `wire` is simply the wrong keyword. The rewrite
    therefore:

    * replaces the edge sensitivity with `@(*)`;
    * replaces non-blocking `<=` with blocking `=` inside that block;
    * changes `output wire` to `output reg` for signals assigned procedurally,
      whether or not an edge block was rewritten.

    Nothing else is touched: not port names, directions, widths or order, not the
    expressions, and not other blocks. A contract that declares a clock is
    returned from the edge rewrite unchanged, so a sequential design can never be
    altered by that part.
    """
    if not rtl:
        return rtl

    declared = declared_ports(rtl)
    result = rtl

    if contract.clock_spec.name not in declared:
        def replace(match: re.Match) -> str:
            body = match.group("body")
            # Only the assignment operator changes; expressions keep their order
            # and parentheses exactly as written.
            body = re.sub(r"<=", "=", body)
            return f"always @(*){body}"

        result = _EDGE_BLOCK_RE.sub(replace, result)

    # Applies regardless of whether an edge block was rewritten, because the two
    # defects are independent.
    return declare_procedural_outputs(result)


def render_findings(findings: list[Finding]) -> str:
    if not findings:
        return ""
    return "\n".join(finding.render() for finding in findings)
