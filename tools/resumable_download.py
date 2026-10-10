"""Resumable downloader that reports progress and survives dropped connections.

The Ollama installer is ~1.5 GB and this network drops the transfer partway
through, so a plain download cannot be relied on. This keeps partial bytes,
resumes with a Range request, and prints progress so a stall is visible instead
of looking like a hang. It also tells the caller whether what arrived is
actually a Windows installer, since a captive portal or an error page can be
served with an HTTP 200.

    py -3 tools/resumable_download.py <url> <destination> [--proxy URL]
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CHUNK = 1024 * 1024
# A Windows PE executable starts with "MZ"; anything else means we were served
# something other than the installer.
PE_MAGIC = b"MZ"
# GitHub's release asset host rejects requests without a User-Agent.
USER_AGENT = "LogicLens-download"


def opener(proxy: str | None) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def remote_size(url: str, open_url, timeout: int) -> int | None:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with open_url(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            return int(length) if length else None
    except Exception:  # noqa: BLE001 - size is optional information
        return None


def download(url: str, destination: Path, proxy: str | None, attempts: int, timeout: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    open_url = opener(proxy).open
    total = remote_size(url, open_url, timeout)
    print(f"target size: {total if total else 'unknown'} bytes")

    for attempt in range(1, attempts + 1):
        have = destination.stat().st_size if destination.is_file() else 0
        if total and have >= total:
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        headers["User-Agent"] = USER_AGENT
        request = urllib.request.Request(url, headers=headers)
        try:
            with open_url(request, timeout=timeout) as response:
                mode = "ab" if have and response.status == 206 else "wb"
                if mode == "wb":
                    have = 0
                started = time.time()
                last_report = started
                with destination.open(mode) as handle:
                    while True:
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        have += len(chunk)
                        now = time.time()
                        if now - last_report >= 5:
                            rate = have / max(now - started, 0.001) / 1e6
                            percent = f"{have / total * 100:5.1f}%" if total else "  ?  "
                            print(f"  {percent}  {have / 1e6:8.1f} MB  {rate:5.2f} MB/s")
                            last_report = now
        except Exception as exc:  # noqa: BLE001 - retried below
            print(f"  attempt {attempt} interrupted: {type(exc).__name__}: {exc}")
            time.sleep(3)
            continue
        if total and have >= total:
            break
        time.sleep(1)

    size = destination.stat().st_size if destination.is_file() else 0
    print(f"final: {size} bytes" + (f" / {total}" if total else ""))
    if total and size < total:
        print("INCOMPLETE")
        return 1
    with destination.open("rb") as handle:
        head = handle.read(2)
    if head != PE_MAGIC:
        print(f"WARNING: file does not start with {PE_MAGIC!r} (got {head!r}); not a Windows executable")
        return 1
    print("OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--proxy", default=None, help="e.g. http://127.0.0.1:7897; omit for direct")
    parser.add_argument("--attempts", type=int, default=60)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    return download(args.url, args.destination, args.proxy, args.attempts, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
