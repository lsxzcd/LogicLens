"""Testbench resolution.

The single insertion point where the flow decides *which* testbench verifies a
candidate. Previously the path `data/examples/counter/tb.v` was hardcoded in
both `controller.py` and `baseline.py`, which meant only the bundled counter
task could ever be graded. Everything now goes through `resolve_testbench`, so
a team can plug in the VerilogEval harness (which ships per-task testbenches
and reference implementations) without touching the agent.

Precedence:

1. an explicit `--testbench` path;
2. a sidecar `<question>.tb.v` next to the question file;
3. a generated testbench (knows a few common behaviours, otherwise smoke only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .task_parser import TaskContract

_SIDECAR_SUFFIXES = (".tb.v", ".tb.sv", "_tb.v", "_test.sv", "_test.v")

# Deterministic simulation clock, in nanoseconds. The synthesis constraint is a
# separate 5 ns requirement and has no bearing on simulation timing.
_SIM_PERIOD_NS = 10.0

# Deterministic self-check bounds, in clock cycles.
_COUNTER_WRAP_CYCLES = 4
_SMOKE_CYCLES = 6

_CLOCK_ALIASES = ("clk", "clock", "clk_i", "i_clk", "sys_clk", "aclk")
_RESET_ALIASES = ("rst_n", "rst", "reset_n", "reset", "nrst", "arst", "areset", "sync_rst")
_ENABLE_ALIASES = ("enable", "en", "ce", "clk_en", "clock_enable", "valid_in")

# Prompt-file naming conventions. VerilogEval stores the task as
# `Prob001_zero_prompt.txt`, so the stem still carries the `_prompt` marker and
# the sibling files must be looked up as `Prob001_zero_test.sv`, not
# `Prob001_zero_prompt_test.sv`.
_PROMPT_STEM_SUFFIXES = ("_prompt",)


def candidate_stems(question_path: Path) -> list[str]:
    """Stems to try when looking for files beside a prompt, most specific first."""
    stem = question_path.stem
    stems = [stem]
    for suffix in _PROMPT_STEM_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stems.append(stem[: -len(suffix)])
    return stems


@dataclass
class TestbenchSpec:
    top: str
    path: Path | None = None
    text: str = ""
    source: str = "none"
    behavior: str = "generic"
    notes: list[str] = field(default_factory=list)
    # Some suites need more than one compilation unit. The VerilogEval
    # testbench, for example, instantiates the reference implementation from a
    # separate `<stem>_ref.sv`; without it elaboration fails with an unknown
    # module, so the extra file has to travel with the testbench.
    extra_sources: list[Path] = field(default_factory=list)
    # The module name the testbench instantiates, when it constrains it.
    dut_module: str = ""
    # The testbench's own top module. VerilogEval uses `tb`, not `<dut>_tb`.
    tb_module: str = ""
    # Set when the testbench only compiles under a relaxed analyzer.
    relax_compile: bool = False

    @property
    def is_generated(self) -> bool:
        return self.path is None

    def materialize(self, directory: Path) -> Path:
        """Return a real file path, writing generated text when needed."""
        if self.path is not None:
            return self.path
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{self.top}.v"
        target.write_text(self.text, encoding="utf-8")
        return target


def detect_dut_module(testbench_text: str) -> str:
    """Return the module name a testbench instantiates, when it names one.

    A testbench that hardcodes `TopModule uut (...)` only works if the design
    under test is called TopModule, so the flow has to honour that instead of
    whatever name the task text suggested.

    Note that a reference implementation is typically instantiated *earlier* in
    the file than the DUT (`RefModule good1` before `TopModule top_module1`),
    so the search must not stop at the first instantiation it finds.
    """
    for candidate in ("TopModule",):
        if re.search(rf"\b{candidate}\s+[A-Za-z_]\w*\s*\(", testbench_text):
            return candidate
    return ""


def detect_tb_module(testbench_text: str) -> str:
    """Return the testbench's own top module name.

    The top is the module that instantiates the DUT. All modules are located
    first, then the region of each one is searched, so a `module stimulus_gen`
    appearing before `module tb` cannot be mistaken for the top.
    """
    declarations = [
        (match.group(1), match.start())
        for match in re.finditer(r"\bmodule\s+([A-Za-z_]\w*)\s*(?:#\s*\([^)]*\)\s*)?[\(;]", testbench_text)
    ]

    dut = detect_dut_module(testbench_text)
    if dut:
        for index, (name, start) in enumerate(declarations):
            end = declarations[index + 1][1] if index + 1 < len(declarations) else len(testbench_text)
            if re.search(rf"\b{dut}\s+[A-Za-z_]\w*\s*\(", testbench_text[start:end]):
                return name

    for name, _ in declarations:
        if name == "tb":
            return "tb"
    for name, _ in declarations:
        if name.endswith("_tb"):
            return name
    return ""


def detect_verilogeval_pass_criterion(testbench_text: str) -> bool:
    """True when the testbench reports via the VerilogEval mismatch counter.

    Those benches never print TEST_PASS; the verdict is the `Mismatches: N in
    M samples` line in their final block, and passing means N == 0. The
    counter appears either as a `$display` format string (`%1d`) or already
    rendered, so both spellings are matched.
    """
    pattern = r"Mismatches:\s*(?:%?\d*d\s+in\s+%?\d*d|\d+\s+in\s+\d+)"
    return bool(re.search(pattern, testbench_text))


def _apply_sidecar_metadata(spec: TestbenchSpec, reference: Path | None) -> TestbenchSpec:
    """Read the sidecar testbench once to learn how it must be driven."""
    if spec.path is None:
        return spec
    text = spec.path.read_text(encoding="utf-8", errors="replace")
    if reference is not None:
        spec.extra_sources = [reference]
    spec.dut_module = detect_dut_module(text)
    spec.tb_module = detect_tb_module(text)
    if spec.dut_module:
        spec.top = spec.tb_module or spec.top
        # These benches are written for a lenient analyzer: VerilogEval's
        # `$dumpvars(..., tb_mismatch)` names a wire declared a few lines below,
        # which xvlog rejects unless strict checking is relaxed. Requested only
        # for this shape, so ordinary designs still get full syntax checking.
        if detect_verilogeval_pass_criterion(text):
            spec.relax_compile = True
        if reference is not None:
            spec.notes.append(
                f"testbench instantiates {spec.dut_module}; a reference implementation is compiled alongside it"
            )
            spec.behavior = "reference-compare"
    return spec


def find_port_name(contract: TaskContract, aliases: tuple[str, ...]) -> str | None:
    """Pick the port that actually plays a role, honouring the contract."""
    names = contract.port_names()
    for alias in aliases:
        if alias in names:
            return alias
    for alias in aliases:
        for name in names:
            if name.lower() == alias.lower():
                return name
    return None


def detect_behavior(contract: TaskContract, rtl_text: str) -> str:
    """Classify the DUT well enough to choose a self-checking testbench."""
    lowered = contract.raw_text.lower()
    counter_like = any(
        marker in lowered for marker in ("counter", "计数", "count up", "up counter", "递增", "加 1", "加1")
    )
    has_sequencing = "always" in rtl_text and "posedge" in rtl_text
    clock = find_port_name(contract, _CLOCK_ALIASES)
    reset = find_port_name(contract, _RESET_ALIASES)
    if counter_like and has_sequencing and clock and reset:
        return "counter"
    return "smoke"


def _port_decl(port) -> str:
    width = f" {port.width_range()}" if port.width_range() else ""
    return f"    {port.direction} wire{width} {port.name}"


def generate_testbench(contract: TaskContract, behavior: str, period_ns: float = _SIM_PERIOD_NS) -> TestbenchSpec:
    """Emit a self-checking testbench for the contract's interface."""
    top = contract.top_module
    tb_top = contract.testbench_top or f"{top}_tb"
    notes: list[str] = []

    inputs = [p for p in contract.ports if p.direction == "input"]
    outputs = [p for p in contract.ports if p.direction == "output"]
    if not inputs and not outputs:
        # No interface could be established, so the safest emitted testbench
        # only exercises time; it can never report a false pass because it
        # never prints TEST_PASS.
        body = (
            "    initial begin\n"
            f"        #{_SMOKE_CYCLES * 5};\n"
            '        $display("TB_INCONCLUSIVE: no port list was derived from the task");\n'
            "        $finish;\n"
            "    end\n"
        )
        notes.append("no ports derived; emitted an inconclusive testbench")
        return TestbenchSpec(
            top=tb_top,
            text=_render(tb_top, top, [], [], None, None, body, design_ports=[]),
            source="generated",
            behavior="inconclusive",
            notes=notes,
        )

    clock = find_port_name(contract, _CLOCK_ALIASES)
    reset = find_port_name(contract, _RESET_ALIASES)
    output = outputs[0] if outputs else None

    if behavior == "counter" and clock and reset and output is not None:
        # A task that holds its value while enable is low needs enable raised
        # during the increment phase, or a correct design would be failed.
        holds_when_low = "enable_hold" in contract.boundaries or "enable_gated" in contract.boundaries
        enable = find_port_name(contract, _ENABLE_ALIASES) if holds_when_low else None
        body = _counter_body(contract, clock, reset, output.name, output.width, enable)
        if enable:
            notes.append(f"drives {enable} high during the increment phase ({'+'.join(contract.boundaries)})")
        notes.append(f"self-checking reset-bounded counter check on {output.name}[{output.width}]")
    else:
        body = _smoke_body(clock, inputs)
        if behavior != "counter":
            notes.append("no behaviour-specific check available; emitted a clocked smoke test")

    text = _render(tb_top, top, inputs, outputs, clock, reset, body, design_ports=contract.ports, period_ns=period_ns)
    return TestbenchSpec(top=tb_top, text=text, source="generated", behavior=behavior, notes=notes)


def _counter_body(contract: TaskContract, clock: str, reset: str, output: str, width: int, enable: str | None) -> str:
    """Drive and check a reset-bounded up counter.

    The reference clock is 10 ns and the reset is released at 7 ns, so the
    check at 7 ns still precedes the first active edge at 10 ns and must see
    zero. Sampling at 11 ns, 21 ns, ... observes the value each edge produced.
    Absolute times are used so no checker can race an edge, which is what
    previously failed a correct design.

    When the task says the counter holds while enable is low, a hold check
    follows every increment: without it a module that ignores enable entirely
    would still be accepted, which is exactly the defect a generated grader
    must catch.
    """
    rst_active = "1'b0" if contract.reset_spec.polarity == "low" else "1'b1"
    rst_inactive = "1'b1" if contract.reset_spec.polarity == "low" else "1'b0"
    checks = max(1, min(_COUNTER_WRAP_CYCLES, max(1, width)))
    half = _SIM_PERIOD_NS / 2
    period = _SIM_PERIOD_NS
    lines = [
        "    initial begin",
        f"        {clock} = 1'b0;",
        f"        {reset} = {rst_active};",
    ]
    if enable:
        lines.append(f"        {enable} = 1'b0;")
    lines += [
        f"        #{period:g};",
        f"        if ({output} !== {width}'d0) $fatal(1, \"reset did not clear {output}\");",
        f"        {reset} = {rst_inactive};",
    ]
    if enable:
        lines.append(f"        {enable} = 1'b1;")
    lines += [
        f"        #{half:g};",
        f"        if ({output} !== {width}'d0) $fatal(1, \"{output} moved before the first active edge\");",
    ]
    for step in range(1, checks + 1):
        lines += [
            f"        #{period:g};",
            f"        if ({output} !== {width}'d{step}) $fatal(1, \"{output} expected {step} after {step} edge(s)\");",
        ]
        if enable and step < checks:
            # Enable low for two whole periods; the value must not change.
            lines += [
                f"        {enable} = 1'b0;",
                f"        #{2 * period:g};",
                f"        if ({output} !== {width}'d{step}) $fatal(1, \"{output} changed while {enable} was low\");",
                f"        {enable} = 1'b1;",
            ]
    lines += [
        "",
        '        $display("TEST_PASS");',
        "        $finish;",
        "    end",
    ]
    return "\n".join(lines) + "\n"


def _smoke_body(clock: str | None, inputs: list) -> str:
    lines = ["    initial begin"]
    for port in inputs:
        if clock and port.name == clock:
            continue
        lines.append(f"        {port.name} = {port.width}'d0;")
    if clock:
        lines.append(f"        {clock} = 1'b0;")
        lines.append(f"        repeat ({_SMOKE_CYCLES}) @(posedge {clock});")
        lines.append("        #1;")
        lines.append(f'        repeat ({_SMOKE_CYCLES}) @(posedge {clock});')
        lines.append("        #1;")
    else:
        lines.append(f"        #{_SMOKE_CYCLES};")
    lines += [
        '        $display("TEST_PASS");',
        "        $finish;",
        "    end",
    ]
    return "\n".join(lines) + "\n"


def _render(
    tb_top: str,
    top: str,
    inputs: list,
    outputs: list,
    clock: str | None,
    reset: str | None,
    body: str,
    design_ports: list,
    period_ns: float = _SIM_PERIOD_NS,
) -> str:
    lines = ["`timescale 1ns/1ps", "", f"module {tb_top};"]
    for port in inputs:
        width = f" {port.width_range()}" if port.width_range() else ""
        lines.append(f"    reg{width} {port.name};")
    for port in outputs:
        width = f" {port.width_range()}" if port.width_range() else ""
        lines.append(f"    wire{width} {port.name};")
    lines.append("")
    connections = ", ".join(f".{p.name}({p.name})" for p in design_ports if p.direction in ("input", "output"))
    lines.append(f"    {top} dut ({connections});")

    if clock and any(p.name == clock for p in inputs):
        lines += ["", f"    always #{period_ns / 2:g} {clock} = ~{clock};"]

    lines += ["", body.rstrip("\n"), "endmodule", ""]
    return "\n".join(lines)


def generate_from_contract(contract: TaskContract, rtl_text: str = "") -> TestbenchSpec:
    behavior = detect_behavior(contract, rtl_text)
    return generate_testbench(contract, behavior)


def find_sidecar_testbench(question_path: Path) -> TestbenchSpec | None:
    for stem in candidate_stems(question_path):
        for suffix in _SIDECAR_SUFFIXES:
            candidate = question_path.with_name(stem + suffix)
            if candidate.is_file():
                return TestbenchSpec(
                    top="",
                    path=candidate,
                    source="sidecar",
                    notes=[f"picked up sidecar testbench {candidate.name}"],
                )
    return None


def resolve_reference_answer(question_path: Path) -> Path | None:
    """Find a reference implementation for `--mock` runs.

    A sidecar `<question>.answer.v` sits beside the task prompt, which lets a
    mock run exercise any task instead of only the bundled counter. The
    VerilogEval `<stem>_ref.sv` form is accepted too.
    """
    for stem in candidate_stems(question_path):
        for suffix in (".answer.v", "_ref.sv", ".ref.v"):
            candidate = question_path.with_name(stem + suffix)
            if candidate.is_file():
                return candidate
    return None


def resolve_testbench(
    project_root: Path,
    question_path: Path,
    contract: TaskContract,
    rtl_text: str = "",
    mode: str = "auto",
    explicit: Path | None = None,
) -> TestbenchSpec:
    """Decide which testbench verifies the candidate for this task.

    `mode` is "auto", "sidecar" or "generated". In "auto" the explicit path
    wins, then a sidecar file, then generation.
    """
    if mode not in ("auto", "sidecar", "generated"):
        raise ValueError(f"unknown testbench mode: {mode!r}")

    if mode in ("auto", "sidecar") and explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"testbench not found: {explicit}")
        spec = TestbenchSpec(
            top=contract.testbench_top,
            path=explicit,
            source="explicit",
            notes=[f"using explicit testbench {explicit}"],
        )
        return _apply_sidecar_metadata(spec, resolve_reference_answer(question_path))

    if mode in ("auto", "sidecar"):
        sidecar = find_sidecar_testbench(question_path)
        if sidecar is not None:
            sidecar.top = sidecar.top or contract.testbench_top
            return _apply_sidecar_metadata(sidecar, resolve_reference_answer(question_path))

    generated = generate_from_contract(contract, rtl_text)
    return generated
