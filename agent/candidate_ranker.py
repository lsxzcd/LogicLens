from __future__ import annotations


def synthesis_credit(result: dict) -> bool:
    """Whether a synthesis pass may be credited to the design.

    Synthesis is gated on simulation, so a result with synthesis_attempted
    false never produced a netlist and must not count as a synthesis pass.
    Results predating the field (and mock results) keep their historical
    meaning.
    """
    return bool(result.get("synthesis_pass")) and bool(result.get("synthesis_attempted", True))


def score_result(result: dict, attempt: int) -> tuple[int, int, int]:
    """Higher is better; prefer the deepest verification stage, then fewer attempts."""
    stage = 0
    if result.get("compile_pass"):
        stage = 1
    if result.get("elaborate_pass"):
        stage = 2
    if result.get("simulation_pass"):
        stage = 3
    if synthesis_credit(result):
        stage = 4
    return stage, int(synthesis_credit(result)), -attempt
