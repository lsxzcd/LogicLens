"""Fetch one VerilogEval v2 spec-to-rtl problem triple into a fixture directory.

Kept as a script rather than a manual download so the provenance of the
vendored fixture is reproducible:

    py -3 tools/fetch_verilogeval_problem.py Prob001_zero experiments/data/verilogeval

Writes <dir>/examples/<stem>_prompt.txt, _test.sv and _ref.sv. The flow reads
the prompt as the task and the other two as the official testbench and
reference implementation.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/NVlabs/verilog-eval/main/dataset_spec-to-rtl"
SUFFIXES = ("_prompt.txt", "_test.sv", "_ref.sv")


def fetch(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "LogicLens-dataset-fetch"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_problem_list() -> list[str]:
    """Read problems.txt, the upstream list of every spec-to-rtl stem."""
    payload = fetch(f"{RAW}/problems.txt").decode("utf-8")
    stems = [line.strip() for line in payload.splitlines() if line.strip()]
    return stems


def fetch_triple(stem: str, target: Path, quiet: bool = False) -> int:
    """Fetch the three files for one problem. Returns the number of failures."""
    failures = 0
    for suffix in SUFFIXES:
        url = f"{RAW}/{stem}{suffix}"
        destination = target / f"{stem}{suffix}"
        try:
            payload = fetch(url)
        except urllib.error.HTTPError as exc:
            print(f"  FAILED {stem}{suffix}: HTTP {exc.code}")
            failures += 1
            continue
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  FAILED {stem}{suffix}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        target.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        if not quiet:
            print(f"  saved  {destination.name}  ({len(payload)} bytes)")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch VerilogEval v2 spec-to-rtl problems")
    parser.add_argument("stem", nargs="?", help="Problem stem, e.g. Prob001_zero")
    parser.add_argument("out_dir", type=Path, help="Dataset root; files go into <out_dir>/examples/")
    parser.add_argument("--all", action="store_true", help="Fetch every problem listed in problems.txt")
    parser.add_argument("--list", action="store_true", help="Only print what would be fetched")
    args = parser.parse_args()

    if not args.all and not args.stem:
        parser.error("give a problem stem, or pass --all")

    if args.all:
        try:
            stems = fetch_problem_list()
        except Exception as exc:  # noqa: BLE001 - reported to the user
            print(f"FAILED to read problems.txt: {type(exc).__name__}: {exc}")
            print("Fetch it in a browser, or pass an explicit stem instead.")
            return 1
        print(f"problems.txt lists {len(stems)} problem(s)")
    else:
        stems = [args.stem]

    if args.list:
        for stem in stems:
            for suffix in SUFFIXES:
                print(f"  would fetch {RAW}/{stem}{suffix}")
        return 0

    target = args.out_dir.resolve() / "examples"
    print(f"source : {RAW}")
    print(f"target : {target}")

    failures = 0
    for index, stem in enumerate(stems, start=1):
        if args.all and index % 20 == 1:
            print(f"  [{index}/{len(stems)}] {stem}")
        failures += fetch_triple(stem, target, quiet=args.all)

    if failures:
        print(f"\n{failures} file(s) could not be fetched.")
        print("If the network blocks raw.githubusercontent.com, fetch them in a browser and")
        print(f"place them in {target} with the same names.")
        return 1

    print(f"\nDone: {len(stems) * len(SUFFIXES)} file(s) for {len(stems)} problem(s).")
    print("Inspect with: py -3 tools/check_dataset.py", args.out_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
