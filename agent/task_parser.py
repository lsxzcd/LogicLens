"""Structured specification contract extraction.

Stage one of the agent's pipeline: turn a natural-language RTL task into a
machine-checkable contract (ports, widths, clock, reset, boundary conditions)
before any code is generated.

The rule-based pass here is deliberately deterministic and offline: it is
testable, explainable, and never invents a port it cannot find. Anything it
cannot determine stays unset (`ports` empty, `reset_polarity` unknown) rather
than being guessed, so a downstream model-assisted pass can fill the gaps and
callers can tell the difference between "known" and "assumed".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

DEFAULT_PART = "xczu3eg-sbva484-1-e"
DEFAULT_CLOCK_PERIOD_NS = 5.0

TRISTATE = "tristate"
_KNOWN_DIRECTIONS = ("input", "output", "inout")


@dataclass
class PortSpec:
    name: str
    direction: str = "input"
    width: int = 1
    endian: str = "lsb"
    signed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def width_range(self) -> str:
        if self.direction == TRISTATE:
            return ""
        if self.width <= 1:
            return ""
        if self.endian == "msb":
            return f"[0:{self.width - 1}]"
        return f"[{self.width - 1}:0]"


@dataclass
class ClockSpec:
    name: str = "clk"
    period_ns: float = DEFAULT_CLOCK_PERIOD_NS
    edge: str = "posedge"
    source: str = "default"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResetSpec:
    name: str = "rst_n"
    polarity: str = "low"
    style: str = "sync"
    source: str = "default"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TestbenchContract:
    top: str = ""
    behavior: str = "generic"
    expects_test_pass: bool = True
    source: str = "none"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskContract:
    raw_text: str
    language: str = "Verilog"
    top_module: str = "counter"
    testbench_top: str = "counter_tb"
    # Kept for backward compatibility with the first contract shape. New code
    # should read clock.name / reset.name and the ports list.
    clock: str = "clk"
    reset: str = "rst_n"
    target_part: str = DEFAULT_PART
    clock_period_ns: float = DEFAULT_CLOCK_PERIOD_NS
    ports: list[PortSpec] = field(default_factory=list)
    clock_spec: ClockSpec = field(default_factory=ClockSpec)
    reset_spec: ResetSpec = field(default_factory=ResetSpec)
    boundaries: list[str] = field(default_factory=list)
    testbench: TestbenchContract = field(default_factory=TestbenchContract)
    # True when no module name could be derived from the text. Callers that
    # know the naming convention of their dataset can substitute their own
    # default instead of accepting `top_module`'s placeholder.
    top_module_is_default: bool = False

    def to_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "language": self.language,
            "top_module": self.top_module,
            "testbench_top": self.testbench_top,
            "clock": self.clock,
            "reset": self.reset,
            "target_part": self.target_part,
            "clock_period_ns": self.clock_period_ns,
            "ports": [p.to_dict() for p in self.ports],
            "clock_spec": self.clock_spec.to_dict(),
            "reset_spec": self.reset_spec.to_dict(),
            "boundaries": list(self.boundaries),
            "testbench": self.testbench.to_dict(),
        }

    def port(self, name: str) -> PortSpec | None:
        for item in self.ports:
            if item.name == name:
                return item
        return None

    def port_names(self) -> list[str]:
        return [p.name for p in self.ports]

    def direction_of(self, name: str) -> str:
        item = self.port(name)
        return item.direction if item else ""

    @property
    def has_clock(self) -> bool:
        return any(p.name == self.clock_spec.name and p.direction in ("input", "inout") for p in self.ports)


def _find_first_identifier(patterns: tuple[str, ...], text: str, flags: int = re.I) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1)
    return None


def _parse_language(lowered: str, text: str) -> str:
    if "systemverilog" in lowered or re.search(r"\.sv\b", text):
        return "SystemVerilog"
    return "Verilog"


def _parse_top_module(text: str) -> str | None:
    # "named X" and "called X" are the most explicit module-name statements, so
    # they are tried before the looser "module X" form. The parenthesis form
    # requires a real parameter or port list opening right after the name, or
    # prose such as "top-level module name is sel" would match on the word
    # "name".
    explicit = _find_first_identifier(
        (
            # "named"/"called" must match the whole word: a plain "named?" also
            # matches "name" (a prefix), so "module name is alu_comb" would
            # capture "is" as the module name. The trailing comma/space is what
            # makes the word complete.
            r"\bmodule\b\s+(?:named|called)(?=[\s,:])[\s:]*[`\"']?([A-Za-z_]\w*)",
            r"\bmodule\b\s+([A-Za-z_]\w*)\s*[(#]",
            # "module X with ..." is an extremely common way to state the top
            # module. The lookahead prevents matching the bare prose
            # "module has ports", which names no module at all.
            r"\bmodule\b\s+([A-Za-z_]\w*)\s+(?=with\b|where\b|that\b|which\b|and\b|,|\.)",
        ),
        text,
    )
    if explicit:
        return explicit
    return _find_first_identifier(
        (
            # "top-level module name is X" names the module explicitly, so it is
            # checked before the Chinese prose forms. The lookahead is required:
            # without it, a prompt saying "consider a top-level module with the
            # following interface" (which names no module) matches on "with".
            r"(?:top(?:-level)?\s+module)\s*(?:name\s*)?(?:is\s*|:\s*)?"
            r"(?!with\b|where\b|that\b|which\b|and\b|the\b|has\b|contains\b)[`\"']?([A-Za-z_]\w*)",
            r"(?:顶层模块|顶层)(?:名称|名字|名)?\s*[为是:：]?\s*([A-Za-z_]\w*)",
            r"模块(?:名称|名字|名)?\s*[为是:：]\s*([A-Za-z_]\w*)",
            r"模块\s+([A-Za-z_]\w*)\s*(?:的|中|里)",
            # A real module header opens a port list or parameter list, so the
            # name must be followed immediately by "(" or "#".
            r"\bmodule\s+(?!has\b|is\b|with\b|contains\b|that\b|which\b|name\b|named\b|the\b|of\b|and\b|or\b)"
            r"(?:name\s*)?(?:is\s*)?[`\"']?([A-Za-z_]\w*)\s*[(#]",
        ),
        text,
    )


def _parse_clock(text: str, lowered: str) -> ClockSpec:
    name = _find_first_identifier(
        (
            r"(输入|端口|信号)?\s*([A-Za-z_]\w*)\s*(?:为|是)\s*(?:上升沿|下降沿)?\s*时钟",
            r"([A-Za-z_]\w*)\s*(?:为|是)\s*(?:上升沿|下降沿)?\s*(?:时钟|clock)",
            r"时钟(?:信号|端口)?\s*[为是:：]?\s*([A-Za-z_]\w*)",
        ),
        text,
    )
    if name and name in ("输入", "端口", "信号"):
        name = None
    if not name:
        # A bare clk/clock mention is the next best deterministic signal.
        if re.search(r"\bclk\b", lowered):
            name = "clk"
        elif re.search(r"\bclock\b", lowered):
            name = "clock"
        elif "时钟" in text:
            name = "clk"
        else:
            name = "clk"
    source = "rule" if name else "default"

    edge = "posedge"
    if re.search(r"下降沿|negedge|负沿", text, re.I):
        edge = "negedge"

    period = DEFAULT_CLOCK_PERIOD_NS
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:ns|纳秒)", text, re.I)
    if match:
        try:
            period = float(match.group(1))
        except ValueError:
            period = DEFAULT_CLOCK_PERIOD_NS
    return ClockSpec(name=name, period_ns=period, edge=edge, source=source)


def _parse_reset(text: str, lowered: str) -> ResetSpec:
    name = _find_first_identifier(
        (
            r"(rst_n|rst|reset_n|reset|nrst|arst|areset)\s*(?:为|是)",
            r"(?:复位|reset)(?:信号|端口)?\s*[为是:：]?\s*(rst_n|rst|reset_n|reset|nrst|arst|areset)",
        ),
        text,
    )
    if not name:
        match = re.search(r"\b(rst_n|rst|reset_n|reset|nrst|arst|areset)\b", text, re.I)
        name = match.group(1) if match else None
    source = "rule" if name else "default"
    if not name:
        name = "rst_n"

    low_markers = ("低有效", "低电平有效", "active low", "active-low", "负有效", "低电平复位")
    high_markers = ("高有效", "高电平有效", "active high", "active-high", "正有效")
    polarity_source = "default"
    if any(marker in lowered or marker in text for marker in low_markers) or name.endswith("_n"):
        polarity = "low"
        polarity_source = "rule"
    elif any(marker in lowered or marker in text for marker in high_markers):
        polarity = "high"
        polarity_source = "rule"
    else:
        polarity = "low" if name.endswith("_n") else "high"

    style = "async" if re.search(r"异步", text) else "sync"
    return ResetSpec(name=name, polarity=polarity, style=style, source=f"{source}/{polarity_source}")


# Field-shaped descriptions such as "output reg [7:0] count" or "input clk".
_STRUCTURED_PORT_RE = re.compile(
    r"\b(input|output|inout)\b\s*(?P<type>wire|reg|logic|bit)?\s*"
    r"(?P<width>\[\s*\d+\s*:\s*\d+\s*\])?\s*(?P<name>[A-Za-z_]\w*)",
    re.I,
)

# Keyword-driven fallback for prose specifications that never name a direction.
_PORT_KEYWORDS: tuple[tuple[tuple[str, ...], str, int], ...] = (
    (("enable", "en"), "enable", 1),
    (("rst_n", "reset_n", "nrst", "arst", "areset", "rst", "reset"), "reset", 1),
    (("clk", "clock"), "clock", 1),
    (("count",), "count", 0),
    (("done",), "done", 1),
    (("valid",), "valid", 1),
    (("ready",), "ready", 1),
)


def _parse_width_from_text(text: str, start: int, end: int, default: int, allow_lookbehind: bool = True) -> int:
    """Find a width stated for one specific mention of a signal.

    Verilog states a width before the name it qualifies ("[7:0] din",
    "8-bit output y"), so a width written before this mention is authoritative
    and the lookbehind is consulted first. The lookbehind is limited to the
    current clause, which stops a width from an earlier sentence - or a
    neighbouring port's, on the other side of a comma - leaking onto this name.
    Only when nothing precedes the name is the text that follows it examined.
    """
    if allow_lookbehind:
        behind = text[max(0, start - 48) : start]
        clause_break = max(behind.rfind(separator) for separator in (",", "，", "；", ";", "\n", "。"))
        if clause_break >= 0:
            behind = behind[clause_break + 1 :]
        match = re.search(r"\[\s*\d+\s*:\s*\d+\s*\]\s*$", behind)
        if match:
            return width_from_bracket(match.group(0)) or 1
        match = re.search(r"(\d+)\s*(?:位|bit|bits|-bit)\s*$", behind, re.I)
        if match:
            return int(match.group(1))

    forward = text[start:end]
    match = re.search(r"\[\s*\d+\s*:\s*\d+\s*\]", forward)
    if match:
        return width_from_bracket(match.group(0)) or 1

    # A width stated after the name must be adjacent to it, so "output count,
    # width 8 bits" resolves while a later port's width does not.
    tail = text[end:]
    stop = len(tail)
    for separator in (",", "，", "；", ";", "\n", "。"):
        position = tail.find(separator)
        if 0 <= position < stop:
            stop = position
    if stop == 0:
        return default
    tail = tail[:stop]
    match = re.search(r"(?:宽度|位宽|width)\s*(?:为|是|:：|=)?\s*(\d+)", tail, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:为|是|:：|=)\s*(\d+)\s*(?:位|bit|bits|-bit)", tail, re.I)
    if match:
        return int(match.group(1))
    return default


def ports_from_structured_text(text: str) -> list[PortSpec]:
    """Parse declarations that carry an explicit width bracket.

    The width bracket is required on purpose: "output q, width 4 bits" is prose
    that merely mentions a direction, and accepting it here would shadow the
    prose parser with a less accurate result.
    """
    ports: list[PortSpec] = []
    seen: set[str] = set()
    for match in _STRUCTURED_PORT_RE.finditer(text):
        if not match.group("width"):
            continue
        name = match.group("name")
        if name.lower() in _KNOWN_DIRECTIONS or name.lower() in _WORD_STOPLIST or name in seen:
            continue
        seen.add(name)
        width = width_from_bracket(match.group("width")) or 1
        ports.append(
            PortSpec(
                name=name,
                direction=match.group(1).lower(),
                width=width,
                signed=bool(re.search(r"\bsigned\b", match.group(0), re.I)),
            )
        )
    return ports


def ports_from_keyword_declarations(text: str) -> list[PortSpec]:
    """Parse bare declarations such as "input clk" and "output wires y".

    Accepts widths stated in words ("output count, width 8 bits") because the
    direction is explicit for that specific name.
    """
    ports: list[PortSpec] = []
    seen: set[str] = set()
    for match in _STRUCTURED_PORT_RE.finditer(text):
        name = match.group("name")
        if name.lower() in _KNOWN_DIRECTIONS or name.lower() in _WORD_STOPLIST or name in seen:
            continue
        seen.add(name)
        if match.group("width"):
            width = width_from_bracket(match.group("width")) or 1
        else:
            # Stop before the next direction keyword: a width stated there
            # belongs to that declaration, not to this one.
            tail = text[match.end() :]
            next_direction = re.search(r"\b(?:input|output|inout)\b", tail, re.I)
            stop = next_direction.start() if next_direction else len(tail)
            width = _parse_width_from_text(text, match.start(), match.end() + stop, 1)
        ports.append(
            PortSpec(
                name=name,
                direction=match.group(1).lower(),
                width=max(1, width),
                signed=bool(re.search(r"\bsigned\b", match.group(0), re.I)),
            )
        )
    return ports


def ports_from_declaration_list(declaration_text: str) -> list[PortSpec]:
    """Parse an ANSI port list where widths are declared per item.

    Each comma-separated item carries its own direction, so a width is read
    only from that item and never from its neighbour.
    """
    ports: list[PortSpec] = []
    seen: set[str] = set()
    item_start = 0
    for item in _split_top_level_commas(declaration_text):
        match = _STRUCTURED_PORT_RE.search(item)
        if match:
            name = match.group("name")
            if name.lower() not in _KNOWN_DIRECTIONS and name not in seen:
                seen.add(name)
                width = 1
                if match.group("width"):
                    width = width_from_bracket(match.group("width")) or 1
                ports.append(
                    PortSpec(
                        name=name,
                        direction=match.group(1).lower(),
                        width=width,
                        signed=bool(re.search(r"\bsigned\b", match.group(0), re.I)),
                    )
                )
        item_start += len(item) + 1
    _ = item_start
    return ports


def _split_top_level_commas(text: str) -> list[str]:
    items: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            items.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        items.append("".join(current))
    return items


_DIRECTION_WORDS = frozenset({"input", "inputs", "output", "outputs", "inout"})

# The VerilogEval suite states its interface as a hyphen bullet list:
#
#     - input  vec  (3 bits)
#     - output outv (3 bits)
#
# This is the primary interface carrier for that dataset, so it is parsed as a
# first-class form rather than left to the looser prose heuristics.
_BULLET_PORT_RE = re.compile(
    r"^[ \t]*[-*][ \t]*(?P<dir>input|output|inout)\b[ \t]*"
    r"(?P<type>wire|reg|logic|bit)?[ \t]*"
    r"(?P<name>[A-Za-z_]\w*)[ \t]*"
    r"(?P<width>\([^)]*\)|\[[^\]]*\])?",
    re.I | re.M,
)

# Some prompts state the interface as a Verilog snippet instead of a bullet
# list, e.g. "bug fixing" tasks that show the module to repair. The header
# inside that snippet is authoritative. Two spellings occur upstream: a fenced
# code block, and a plainly indented snippet (the HDLBits-derived prompts use
# the indented form).
_CODE_BLOCK_RES = (
    re.compile(r"```[a-zA-Z]*\s*\n(?P<body>.*?)```", re.S),
    re.compile(r"(?P<body>(?:^[ \t]{2,}\S.*\n)+)", re.M),
)
_MODULE_HEADER_RE = re.compile(
    r"\bmodule\s+(?P<name>[A-Za-z_]\w*)\s*(?:#\s*\([^)]*\)\s*)?\((?P<ports>[^;]*?)\)\s*;",
    re.S,
)

# Module names that appear in prompts as context rather than as the deliverable.
_HELPER_MODULE_NAMES = frozenset({"full_module", "refmodule", "reference_module"})

_WORD_STOPLIST = frozenset(
    {
        "port",
        "ports",
        "signal",
        "signals",
        "width",
        "widths",
        "bit",
        "bits",
        "and",
        "or",
        "the",
        "a",
        "an",
        "of",
        "is",
        "are",
        "has",
        "have",
        "with",
        "each",
        "all",
        "named",
        "name",
        "module",
        "wire",
        "reg",
        "logic",
        "signed",
        "unsigned",
        "that",
        "this",
        "to",
        "from",
        "should",
        "value",
        "values",
        "vector",
        "computes",
        "connected",
        "changes",
        "changed",
        "go",
        "half",
        "combinationally",
        "given",
        "following",
        "implement",
        "implementing",
    }
)

# Words that must not be treated as a port name only when no direction
# accompanies them. A port may legitimately be called `a` or `in`, so these are
# applied to the sentence heuristics and never to an explicit `- input a`.
_PROSE_ONLY_STOPLIST = frozenset(
    {"a", "an", "in", "out", "up", "on", "at", "it", "as", "do", "so", "no", "not"}
)

_WIDTH_PHRASE_RE = re.compile(r"\(?\s*(?:width|位宽|宽度)?\s*=?\s*\d+\s*(?:位|bit|bits|-bit)\s*\)?", re.I)


def _strip_width_phrases(text: str) -> str:
    """Remove width annotations so only port names are picked up as identifiers."""
    return _WIDTH_PHRASE_RE.sub(" ", text)


def _read_prose_name_list(after: str, seen: set[str]) -> tuple[list[tuple[str, int]], str | None]:
    """Consume a plain name list from the text following a direction keyword.

    Scanning stops at the first token that is not a bare port name, which is
    what keeps a following "Output q" or a "(posedge)" annotation from being
    absorbed into the previous group's port list. A direction keyword ends the
    list without being consumed, so the caller's scan can pick it up as its own
    group.
    """
    names: list[tuple[str, int]] = []
    pending_width = 1
    position = 0
    length = len(after)
    while position < length:
        match = re.compile(r"\s*[,、&]?\s*(?:and\s+)?").match(after, position)
        if match:
            position = match.end()
        if position >= length:
            break
        width_match = re.compile(r"\(([^)]*)\)").match(after, position)
        if width_match:
            stated = re.search(r"(\d+)", width_match.group(1))
            if stated:
                pending_width = int(stated.group(1))
            position = width_match.end()
            continue
        word_match = re.compile(r"[A-Za-z_]\w*").match(after, position)
        if not word_match:
            break
        word = word_match.group(0)
        if word.lower() in _DIRECTION_WORDS or word.lower() in _WORD_STOPLIST:
            break
        if word not in seen:
            names.append((word, pending_width))
        pending_width = 1
        position = word_match.end()
    return names, None


def ports_from_bullet_list(text: str) -> list[PortSpec]:
    """Parse a hyphen bullet interface, as used by the VerilogEval prompts.

    An explicit direction makes the name a port, so no stoplist applies here: a
    port really may be called `a`, `in` or `out`.
    """
    ports: list[PortSpec] = []
    seen: set[str] = set()
    for match in _BULLET_PORT_RE.finditer(text):
        name = match.group("name")
        if name.lower() in _KNOWN_DIRECTIONS or name in seen:
            continue
        seen.add(name)
        ports.append(
            PortSpec(
                name=name,
                direction=match.group("dir").lower(),
                width=_width_from_annotation(match.group("width")),
            )
        )
    return ports


def width_from_bracket(annotation: str | None) -> int | None:
    """Width of a `[high:low]` range, or None when there is no range.

    The width is |high - low| + 1, not max + 1: both `[7:0]` and `[0:7]` are
    eight bits, and a real upstream task declares `output [3:1] ena`, which is
    three bits. Using max+1 would silently report one bit too many for any
    range that does not start at zero.
    """
    if not annotation or not annotation.strip().startswith("["):
        return None
    numbers = re.findall(r"-?\d+", annotation)
    if len(numbers) < 2:
        if len(numbers) == 1:
            return int(numbers[0]) + 1
        return None
    high, low = int(numbers[0]), int(numbers[1])
    return abs(high - low) + 1


def _width_from_annotation(annotation: str | None) -> int:
    """Read a width from `(3 bits)`, `[7:0]`, `[3:1]` or `(8 bits each)`.

    The VerilogEval prompts annotate every multi-bit port this way and omit the
    annotation for 1-bit ports, so an absent annotation means one bit.
    """
    if not annotation:
        return 1
    bracket = width_from_bracket(annotation)
    if bracket is not None:
        return bracket
    match = re.search(r"(\d+)\s*(?:bits?|位)", annotation, re.I)
    if match:
        return int(match.group(1))
    return 1


def ports_from_prose_list(text: str) -> list[PortSpec]:
    """Parse prose interfaces such as "inputs: a, b and sub" or "input ports clk and rst_n".

    Deliberately narrow. Ordinary prose like "a decoder with 3-bit input sel"
    names a signal inside a sentence, not a port group, so a group is accepted
    only when the text marks it as one: either a colon after the keyword, or an
    explicit "ports"/"signals" noun. A lone name is accepted only with such a
    marker, which keeps sentence nouns out of the interface.
    """
    ports: list[PortSpec] = []
    seen: set[str] = set()
    groups = (
        ("input", r"\b(?:inputs|input\s+(?:ports?|signals?))\b\s*(?P<mark>:|)"),
        ("output", r"\b(?:outputs|output\s+(?:ports?|signals?))\b\s*(?P<mark>:|)"),
    )
    for direction, pattern in groups:
        for match in re.finditer(pattern + r"\s*", text, re.I):
            marked = bool(match.group("mark")) or "port" in match.group(0).lower() or "signal" in match.group(0).lower()
            names, _ = _read_prose_name_list(text[match.end() :], seen)
            if not marked and len(names) < 2:
                continue
            # A width may be stated before the keyword ("8-bit output y"), so a
            # leading qualifier is inherited by the first name in the group.
            leading = re.search(r"(\d+)\s*(?:位|bit|bits|-bit)\s*$", text[: match.start()], re.I)
            for index, (name, width) in enumerate(names):
                if index == 0 and leading:
                    width = int(leading.group(1))
                seen.add(name)
                ports.append(PortSpec(name=name, direction=direction, width=width))
    return ports


def ports_from_keywords(text: str) -> list[PortSpec]:
    """Infer a conventional port set when the task never lists directions.

    Only well-known signal names are recognised, and a width is used only when
    the text states one. Unknown names are never invented, so a caller can tell
    an inferred interface from a specified one by checking `ports`.
    """
    lowered = text.lower()
    ports: list[PortSpec] = []
    seen: set[str] = set()

    for aliases, role, fallback_width in _PORT_KEYWORDS:
        hit_pos = -1
        hit_name = ""
        for alias in aliases:
            position = lowered.find(alias)
            if position >= 0 and (hit_pos < 0 or position < hit_pos):
                hit_pos = position
                hit_name = alias
        if hit_pos < 0:
            continue
        if role == "reset":
            if "reset" in seen:
                continue
            seen.add("reset")
            ports.append(PortSpec(name=hit_name, direction="input", width=1))
            continue
        if role in seen:
            continue
        seen.add(role)
        if role in ("clock", "enable", "valid", "ready", "done"):
            ports.append(PortSpec(name=hit_name, direction="input", width=1))
            continue
        width = _parse_width_from_text(text, hit_pos, hit_pos + len(hit_name), fallback_width or 8)
        ports.append(PortSpec(name=hit_name, direction="output", width=max(1, width)))

    order = {"clock": 0, "reset": 1, "enable": 2, "valid": 3, "ready": 4, "count": 5, "done": 6}
    ports.sort(key=lambda p: order.get(p.name, 99))
    return ports


def ports_from_rtl(rtl_text: str) -> list[PortSpec]:
    """Extract the interface from an already generated module.

    Used to feed the contract back into prompt building and testbench
    selection once a candidate exists.
    """
    match = re.search(r"\bmodule\b\s+[A-Za-z_]\w*\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;", rtl_text, re.S | re.I)
    if not match:
        return []
    return ports_from_declaration_list(match.group(1))


def parse_boundaries(text: str) -> list[str]:
    """Collect explicit ordering/edge requirements worth checking later."""
    found: list[str] = []
    rules = (
        ("enable_hold", r"enable\s*(?:为|是|=)\s*0\s*时\s*(?:保持|不变)|保持原值|hold(?:s)? (?:its|the) value|remains? unchanged"),
        ("enable_gated", r"enable\s*(?:为|是|=)\s*1\s*时"),
        ("saturate", r"饱和|saturat"),
        ("wrap", r"回绕|溢出后归零|wrap(?:s)? around|roll(?:s)? over"),
        ("overflow_drop", r"丢弃溢出|discard (?:the )?overflow|ignore (?:the )?overflow"),
        ("shift_in_zero", r"补\s*0|shift in zeros|zero fill"),
        ("one_hot", r"独热|one[- ]hot"),
    )
    for name, pattern in rules:
        if re.search(pattern, text, re.I):
            found.append(name)
    return found


def parse_task(text: str) -> TaskContract:
    """Rule-based extraction of the specification contract.

    Deterministic and offline. Fields this pass cannot establish are left at
    their defaults with `source == "default"` so that a model-assisted pass
    (`parse_task_with_model`) can be layered on top and callers can detect
    which values were actually derived from the task text.
    """
    lowered = text.lower()
    parsed_top = _parse_top_module(text)
    top = parsed_top or "counter"
    tb_top = _find_first_identifier(
        (
            r"(?:测试台|testbench|tb)(?:模块)?(?:名称|名字|名)?\s*[为是:：]?\s*([A-Za-z_]\w*)",
            r"module\s+([A-Za-z_]\w*_tb)\b",
        ),
        text,
    ) or f"{top}_tb"

    clock_spec = _parse_clock(text, lowered)
    reset_spec = _parse_reset(text, lowered)

    ports = ports_from_bullet_list(text)
    # A bullet list is the authoritative interface statement. A code block in
    # the same prompt is often context rather than the interface: one upstream
    # task states the interface as bullets and then shows a `full_module`
    # helper it explicitly says the solver need not produce. Only fall through
    # to the snippet when no bullet list exists.
    if not ports:
        block_module, block_ports = ports_from_code_block(text)
        if block_ports:
            ports = block_ports
            if block_module and block_module.lower() not in _HELPER_MODULE_NAMES:
                top = block_module
                tb_top = f"{block_module}_tb"
    if not ports:
        ports = ports_from_structured_text(text)
    if not ports:
        ports = ports_from_prose_list(text)
    if not ports:
        ports = ports_from_keyword_declarations(text)
    if not ports:
        ports = ports_from_keywords(text)

    return TaskContract(
        raw_text=text,
        language=_parse_language(lowered, text),
        top_module=top,
        testbench_top=tb_top,
        clock=clock_spec.name,
        reset=reset_spec.name,
        clock_period_ns=clock_spec.period_ns,
        ports=ports,
        clock_spec=clock_spec,
        reset_spec=reset_spec,
        boundaries=parse_boundaries(text),
        testbench=_parse_testbench(text),
        top_module_is_default=parsed_top is None,
    )


def _parse_testbench(text: str) -> TestbenchContract:
    """Detect an explicitly named testbench before falling back to generation."""
    tb_top = _find_first_identifier(
        (
            r"(?:测试台|testbench|tb)(?:模块)?(?:名称|名字|名)?\s*[为是:：]\s*([A-Za-z_]\w*)",
            r"module\s+([A-Za-z_]\w*_tb)\b",
        ),
        text,
    )
    if tb_top:
        return TestbenchContract(top=tb_top, source="text")
    return TestbenchContract()


def ports_from_code_block(text: str) -> tuple[str, list[PortSpec]]:
    """Parse an interface shown as a Verilog module header in a snippet.

    Returns (module_name, ports); both empty when no such snippet exists.
    """
    for pattern in _CODE_BLOCK_RES:
        for block in pattern.finditer(text):
            header = _MODULE_HEADER_RE.search(block.group("body"))
            if not header:
                continue
            declaration = " ".join(header.group("ports").split())
            ports = ports_from_declaration_list(declaration)
            if ports:
                return header.group("name"), ports
    return "", []


def parse_task_with_model(text: str, client) -> TaskContract:
    """Model-assisted fallback for what the rule pass could not determine.

    Placeholder integration point: it currently returns the rule-based
    contract unchanged. A team implementing the model pass should fill in
    `ports` and any `source == "default"` field from a validated JSON reply,
    keeping the rule-based values whenever they exist.
    """
    contract = parse_task(text)
    if contract.ports:
        return contract
    prompt = (
        "Extract the RTL module interface as JSON. Reply with an object of the form "
        '{"ports": [{"name": "clk", "direction": "input", "width": 1}]} '
        "and nothing else.\n\nTask:\n" + text
    )
    _ = (client, prompt)
    return contract
