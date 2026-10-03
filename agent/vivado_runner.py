from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 900

# Last-resort locations, only consulted after PATH and the environment
# override, so a contributor is not required to edit this list.
_FALLBACK_VIVADO_PATHS = (
    r"D:\2025.2\Vivado\bin\vivado.bat",
    r"C:\Xilinx\Vivado\2025.2\bin\vivado.bat",
    r"D:\Xilinx\Vivado\2025.2\bin\vivado.bat",
    "/tools/Xilinx/Vivado/2025.2/bin/vivado",
    "/opt/Xilinx/Vivado/2025.2/bin/vivado",
)


def vivado_candidates(explicit: str | None = None) -> list[str]:
    """Every place a Vivado executable may be found, in priority order."""
    candidates: list[str] = []
    if explicit:
        return [explicit]
    env = os.getenv("LOGICLENS_VIVADO")
    if env:
        candidates.append(env)
    for name in ("vivado", "vivado.bat"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    candidates.extend(_FALLBACK_VIVADO_PATHS)
    return candidates


def locate_vivado(explicit: str | None = None) -> str | None:
    """Resolve the Vivado executable, or None when this host has none."""
    if explicit:
        return explicit
    for candidate in vivado_candidates():
        if shutil.which(candidate) or Path(candidate).is_file():
            return candidate
    return None


def _failure(reason: str, tool: str, elapsed: float, log: str = "") -> dict:
    return {
        "compile_pass": False,
        "elaborate_pass": False,
        "simulation_pass": False,
        "sim_crashed": False,
        "synthesis_attempted": False,
        "synthesis_pass": False,
        "timing_constraint_pass": False,
        "tool": tool,
        "elapsed_seconds": elapsed,
        "log": log or reason,
    }


def run_vivado_flow(
    project_root: Path,
    rtl_path: Path,
    tb_path: Path,
    tb_top: str,
    top: str,
    run_dir: Path,
    vivado: str | None = None,
    mock: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    extra_sources: list[Path] | None = None,
    relax_compile: bool = False,
) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    if mock:
        result = {
            "compile_pass": True,
            "elaborate_pass": True,
            "simulation_pass": True,
            "sim_crashed": False,
            "synthesis_attempted": True,
            "synthesis_pass": True,
            "timing_constraint_pass": True,
            "tool": "mock",
            "elapsed_seconds": 0.01,
            "log": "MOCK verification passed",
        }
        (run_dir / "flow_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    vivado_bin = locate_vivado(vivado)
    if not vivado_bin:
        result = _failure(
            "Vivado was not found. Set LOGICLENS_VIVADO, add it to PATH, or pass --vivado.",
            "unavailable",
            0.0,
        )
        (run_dir / "flow_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    tcl = project_root / "vivado" / "run_flow.tcl"
    command = [
        vivado_bin,
        "-mode",
        "batch",
        "-nolog",
        "-nojournal",
        "-source",
        str(tcl),
        "-tclargs",
        str(rtl_path),
        str(tb_path),
        tb_top,
        top,
        str(run_dir),
    ]
    # Extra compile units (the reference implementation in VerilogEval-style
    # suites) follow the five positional arguments.
    for source in extra_sources or []:
        command.append(str(source))
    if relax_compile:
        # Some published testbenches rely on a forward reference that only a
        # lenient analyzer accepts (VerilogEval's `$dumpvars(..., tb_mismatch)`
        # names a wire declared a few lines below). xvlog refuses it by default;
        # --relax turns that error into a warning without changing what is
        # compiled, but it is requested per testbench rather than applied to
        # every design, so ordinary syntax errors still fail the compile stage.
        command.append("--relax")
    start = time.perf_counter()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        returncode: int | None = completed.returncode
    except subprocess.TimeoutExpired as expired:
        # A hung tool must not hang the batch run: record the timeout, keep
        # whatever partial output exists, and report the stage as failed.
        timed_out = True
        stdout = _as_text(expired.stdout)
        stderr = _as_text(expired.stderr) + f"\nTIMEOUT after {timeout_seconds}s"
        returncode = None
    elapsed = time.perf_counter() - start
    combined_log = stdout + "\n" + stderr
    (run_dir / "vivado.log").write_text(combined_log, encoding="utf-8")

    result_path = run_dir / "flow_result.json"
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result = _failure("flow_result.json was not valid JSON", vivado_bin, elapsed, combined_log[-10000:])
    else:
        result = _failure("Vivado produced no flow_result.json", vivado_bin, elapsed, combined_log[-10000:])

    if timed_out:
        result.update(
            {
                "compile_pass": False,
                "elaborate_pass": False,
                "simulation_pass": False,
                "sim_crashed": False,
                "synthesis_attempted": False,
                "synthesis_pass": False,
                "timing_constraint_pass": False,
                "timed_out": True,
            }
        )

    stage_logs = []
    for name in ("compile.log", "elaboration.log", "simulation.log", "synthesis.log"):
        stage_path = run_dir / name
        if stage_path.is_file():
            stage_logs.append(f"===== {name} =====\n{stage_path.read_text(encoding='utf-8', errors='replace')}")
    result["log"] = "\n".join(stage_logs) or combined_log[-10000:]
    result["tool"] = vivado_bin
    result["process_returncode"] = returncode
    result.setdefault("timed_out", timed_out)
    result["elapsed_seconds"] = round(elapsed, 3)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
