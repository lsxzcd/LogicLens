"""Finish the Ollama setup: install, pull the model, verify the endpoint.

The installer and the model are large downloads, so they are handled here as
discrete, resumable steps rather than being hidden inside one long action. Run
with --check first to see what is still missing.

    py -3 tools/setup_ollama.py --check
    py -3 tools/setup_ollama.py --installer D:\\JZDSLx\\ollama_location\\OllamaSetup.exe
    py -3 tools/setup_ollama.py --pull deepseek-coder:6.7b
    py -3 tools/setup_ollama.py --verify

Every path is configurable because this machine has only a few GB free on C:,
so both the binaries and the models must live on D:.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_INSTALL_DIR = Path(r"D:\JZDSLx\ollama_location")
DEFAULT_MODELS_DIR = Path(r"D:\JZDSLx\ollama_models")
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "deepseek-coder:6.7b"


def find_ollama(install_dir: Path) -> str | None:
    for candidate in (
        install_dir / "ollama.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(r"C:\Program Files\Ollama\ollama.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ollama")


def server_ready(host: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def list_models(host: str) -> list[str]:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=10) as response:
            import json

            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - reported by the caller as an empty list
        return []
    return [entry.get("name", "") for entry in payload.get("models", [])]


def cmd_check(install_dir: Path, models_dir: Path, host: str, model: str) -> int:
    binary = find_ollama(install_dir)
    env_models = os.environ.get("OLLAMA_MODELS", "")
    print("Ollama setup status")
    print(f"  binary found      : {binary or 'NO'}")
    print(f"  install dir       : {install_dir}  (exists={install_dir.is_dir()})")
    print(f"  models dir        : {models_dir}  (exists={models_dir.is_dir()})")
    print(f"  OLLAMA_MODELS env : {env_models or '(unset)'}")
    ready = server_ready(host)
    print(f"  server on {host}: {'running' if ready else 'not responding'}")
    if ready:
        models = list_models(host)
        print(f"  models available  : {models or 'none'}")
        print(f"  target model      : {model}  ({'present' if model in models else 'NOT pulled'})")

    missing = []
    if not binary:
        missing.append("the Ollama binary (run the installer)")
    if env_models != str(models_dir):
        missing.append(f"OLLAMA_MODELS should be {models_dir}")
    if not ready:
        missing.append("the Ollama server (start the app)")
    if ready and model not in list_models(host):
        missing.append(f"the model {model} (ollama pull {model})")
    print()
    if missing:
        print("Still needed:")
        for item in missing:
            print(f"  - {item}")
        return 1
    print("Everything is in place.")
    return 0


def cmd_installer(path: Path, install_dir: Path) -> int:
    if not path.is_file():
        print(f"installer not found: {path}")
        return 2
    size_mb = path.stat().st_size / 1e6
    print(f"installer : {path}  ({size_mb:.0f} MB)")
    print(f"installing to {install_dir} with /DIR")
    install_dir.mkdir(parents=True, exist_ok=True)
    # The installer does not need administrator rights and accepts /DIR, per
    # https://docs.ollama.com/windows. It is not silent, so the user confirms
    # the dialog that appears.
    completed = subprocess.run([str(path), f"/DIR={install_dir}"], check=False)
    print(f"installer exit code: {completed.returncode}")
    binary = find_ollama(install_dir)
    print(f"binary now at: {binary or 'NOT FOUND'}")
    return 0 if binary else 1


def cmd_pull(binary: str, model: str, models_dir: Path) -> int:
    models_dir.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["OLLAMA_MODELS"] = str(models_dir)
    print(f"pulling {model} into {models_dir}")
    print("this is a multi-GB download; it prints progress below")
    completed = subprocess.run([binary, "pull", model], check=False, env=environment)
    return 0 if completed.returncode == 0 else 1


def cmd_verify(host: str, model: str) -> int:
    # The project's own checker performs the end-to-end request.
    client_args = [sys.executable, str(ROOT / "tools" / "check_model.py")]
    environment = dict(os.environ)
    environment["LOGICLENS_MODEL_URL"] = f"{host}/v1"
    environment["LOGICLENS_MODEL_NAME"] = model
    completed = subprocess.run(client_args, check=False, env=environment)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up and verify a local Ollama server")
    parser.add_argument("--check", action="store_true", help="Report what is still missing")
    parser.add_argument("--installer", type=Path, help="Path to OllamaSetup.exe")
    parser.add_argument("--pull", default=None, metavar="MODEL", help="Model to download")
    parser.add_argument("--verify", action="store_true", help="Run the project's endpoint check")
    parser.add_argument("--start", action="store_true", help="Start the Ollama app if the server is down")
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_INSTALL_DIR)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    if args.installer:
        return cmd_installer(args.installer, args.install_dir)

    if args.pull:
        binary = find_ollama(args.install_dir)
        if not binary:
            print("Ollama binary not found; run --installer first.")
            return 2
        return cmd_pull(binary, args.pull, args.models_dir)

    if args.start:
        binary = find_ollama(args.install_dir)
        if not binary:
            print("Ollama binary not found; run --installer first.")
            return 2
        app = Path(binary).with_name("ollama app.exe")
        target = str(app) if app.is_file() else binary
        print(f"starting {target}")
        subprocess.Popen([target], close_fds=True)  # noqa: S603 - fixed, validated path
        for _ in range(30):
            if server_ready(args.host):
                print("server is responding")
                return 0
            time.sleep(1)
        print("server did not start; check %LOCALAPPDATA%\\Ollama\\app.log")
        return 1

    if args.verify:
        return cmd_verify(args.host, args.model)

    return cmd_check(args.install_dir, args.models_dir, args.host, args.model)


if __name__ == "__main__":
    raise SystemExit(main())
