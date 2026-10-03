#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: ./run_baseline.sh <question.txt> [additional run_baseline.py arguments]" >&2
  exit 2
fi

question_path="$1"
shift
python3 run_baseline.py --question "$question_path" "$@"

