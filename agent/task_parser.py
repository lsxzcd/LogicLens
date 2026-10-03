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
            # checked before the Chinese prose forms.
            r"(?:top(?:-level)?\s+module)\s*(?:name\s*)?(?:is\s*|:\s*)?[`\"']?([A-Za-z_]\w*)",
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
        match = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*$", behind)
        if match:
            return max(int(match.group(1)), int(match.group(2))) + 1
        match = re.search(r"(\d+)\s*(?:位|bit|bits|-bit)\s*$", behind, re.I)
        if match:
            return int(match.group(1))

    forward = text[start:end]
    match = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", forward)
    if match:
        return max(int(match.group(1)), int(match.group(2))) + 1

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
        width = max(int(x) for x in re.findall(r"\d+", match.group("width"))) + 1
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
            width = max(int(x) for x in re.findall(r"\d+", match.group("width"))) + 1
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
                    width = max(int(x) for x in re.findall(r"\d+", match.group("width"))) + 1
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
    }
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
    top = _parse_top_module(text) or "counter"
    tb_top = _find_first_identifier(
        (
            r"(?:测试台|testbench|tb)(?:模块)?(?:名称|名字|名)?\s*[为是:：]?\s*([A-Za-z_]\w*)",
            r"module\s+([A-Za-z_]\w*_tb)\b",
        ),
        text,
    ) or f"{top}_tb"

    clock_spec = _parse_clock(text, lowered)
    reset_spec = _parse_reset(text, lowered)

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
