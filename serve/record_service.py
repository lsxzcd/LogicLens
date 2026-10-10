"""Record what the inference service is actually running.

MODEL.md has to declare the model source, version, quantisation, memory
footprint and context configuration (topic guide 3.1.5.1). Those values are
reported by the server, so they are read from it rather than typed by hand,
which keeps the document truthful when the model or quantisation changes.

`size_vram` is the field that answers the competition's hard constraint - the
model must fit on a single 32 GB card. On a CPU-only host it reports 0, so a
zero is itself informative: it means GPU residency was never exercised.

    py -3 serve/record_service.py --model qwen2.5-coder:1.5b
    py -3 serve/record_service.py --model X --write model/service-measurements.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_HOST = "http://127.0.0.1:11434"


def _get(host: str, path: str, timeout: float = 10.0):
    with urllib.request.urlopen(f"{host}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _load(host: str, model: str, timeout: float = 600.0) -> None:
    """Send one tiny request so the model is resident and /api/ps reports it."""
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{host}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def _gpu_processes() -> str:
    """Best-effort driver report, so the VRAM figure has a second source.

    AMD and NVIDIA report differently and neither is guaranteed to be present,
    so a failure here is recorded as unavailable rather than treated as an error.
    """
    for command, label in (
        (["rocm-smi", "--showmeminfo", "vram"], "rocm-smi"),
        (["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv"], "nvidia-smi"),
    ):
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        if completed.returncode == 0 and completed.stdout.strip():
            # Never treat a probe failure as fatal, but do say which probe failed.
            first = completed.stdout.strip().splitlines()[0]
            return f"{label}: {first.strip()}"
    return f"unavailable (tried rocm-smi and nvidia-smi; neither reported a GPU)"


def collect(host: str, model: str) -> dict:
    report: dict = {"host": host, "model": model}
    try:
        report["server_version"] = _get(host, "/api/version").get("version")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        report["server_version"] = f"unavailable ({type(exc).__name__})"

    try:
        tags = _get(host, "/api/tags")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        report["error"] = f"cannot reach the inference service: {type(exc).__name__}: {exc}"
        return report

    entry = next((m for m in tags.get("models", []) if m.get("name") == model), None)
    if entry is None:
        report["error"] = f"model {model!r} is not present on the server"
        report["models_present"] = [m.get("name") for m in tags.get("models", [])]
        return report

    details = entry.get("details", {})
    report["on_disk_bytes"] = entry.get("size")
    report["digest"] = entry.get("digest")
    report["quantization"] = details.get("quantization_level")
    report["parameter_size"] = details.get("parameter_size")
    report["model_context_length"] = details.get("context_length")

    # Residency: only meaningful once the model has been loaded.
    try:
        _load(host, model)
        ps = _get(host, "/api/ps")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        report["residency"] = f"unavailable ({type(exc).__name__})"
        return report

    loaded = next((m for m in ps.get("models", []) if m.get("model") == model or m.get("name") == model), None)
    if loaded is None:
        report["residency"] = "the server did not report the model as loaded"
        return report

    vram = loaded.get("size_vram")
    report["resident_bytes"] = loaded.get("size")
    report["size_vram_bytes"] = vram
    report["context_length_loaded"] = loaded.get("context_length")
    report["runner"] = loaded.get("runner")
    report["gpu_accelerated"] = bool(vram)
    if not vram:
        report["residency_note"] = (
            "size_vram is 0, so the model is resident in system memory and no GPU "
            "residency was demonstrated. Re-run on the evaluation machine."
        )
    report["driver"] = _gpu_processes()
    return report


def render(report: dict) -> str:
    def mb(value):
        return f"{value / 1e6:.1f} MB" if isinstance(value, (int, float)) and value else "n/a"

    lines = [
        "Inference service measurement",
        f"  host                     : {report.get('host')}",
        f"  server version           : {report.get('server_version')}",
        f"  model                    : {report.get('model')}",
        f"  parameter size           : {report.get('parameter_size')}",
        f"  quantization             : {report.get('quantization')}",
        f"  digest                   : {report.get('digest')}",
        f"  weights on disk          : {mb(report.get('on_disk_bytes'))}",
        f"  resident in memory       : {mb(report.get('resident_bytes'))}",
        f"  resident in VRAM         : {mb(report.get('size_vram_bytes'))}",
        f"  GPU accelerated          : {report.get('gpu_accelerated')}",
        f"  context length (model)   : {report.get('model_context_length')}",
        f"  context length (loaded)  : {report.get('context_length_loaded')}",
        f"  runner                   : {report.get('runner')}",
        f"  driver report            : {report.get('driver')}",
    ]
    if report.get("error"):
        lines.append(f"  ERROR                    : {report['error']}")
    if report.get("models_present"):
        lines.append(f"  models present           : {report['models_present']}")
    if report.get("residency_note"):
        lines.append(f"  note                     : {report['residency_note']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record inference service configuration")
    parser.add_argument("--model", required=True)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--write", type=str, default=None, help="Also write the JSON to this path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = collect(args.host, args.model)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))

    if args.write:
        from pathlib import Path

        path = Path(args.write)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwritten to {path}")

    # A missing model is a real failure; a CPU-only host is reported, not fatal,
    # because that is exactly what the development machine looks like.
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
