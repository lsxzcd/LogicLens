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


def render_findings(findings: list[Finding]) -> str:
    if not findings:
        return ""
    return "\n".join(finding.render() for finding in findings)
