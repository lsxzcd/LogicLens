#!/usr/bin/env bash
# Container entry point: bring up inference, then run the judged entry point.
#
# The guide requires the container to complete the whole job itself, offline
# (3.1.2), so the service is started here rather than assumed. Everything below
# is local: the only endpoint contacted is the inference server on loopback.
#
# Usage (as the image's ENTRYPOINT):
#   entrypoint.sh <question.txt> [run.py arguments...]
#   entrypoint.sh --check          verify the container is ready without running
set -euo pipefail

cd /opt/logiclens

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }

if [ "${1:-}" = "--check" ]; then
    log "container self-check"
    python3 -c "import sys; print('python', '.'.join(map(str, sys.version_info[:3])))"
    find /models -maxdepth 1 -mindepth 1 -print -quit | grep -q . \
        && log "model weights present in /models" \
        || { log "FAILED: /models is empty; the offline sandbox cannot download weights"; exit 1; }
    python3 -m unittest discover -s tests 2>&1 | tail -3
    log "self-check finished"
    exit 0
fi

if [ $# -lt 1 ]; then
    log "usage: entrypoint.sh <question.txt> [run.py arguments...]"
    exit 2
fi

question="$1"
shift || true

if [ ! -f "$question" ]; then
    log "question file not found: $question"
    exit 2
fi

# Start inference in the background and wait for readiness. start.sh is blocking
# by design for interactive use, so the server is launched directly here and
# polled, which also keeps this script usable as an ENTRYPOINT.
model="${LOGICLENS_MODEL_NAME:-qwen2.5-coder:1.5b}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/models}"

if ! find "$OLLAMA_MODELS" -maxdepth 1 -mindepth 1 -print -quit | grep -q .; then
    log "FAILED: no model weights in $OLLAMA_MODELS"
    log "the evaluation sandbox has no network, so weights must be present before the run"
    exit 1
fi

binary="${OLLAMA_BINARY:-ollama}"
if ! command -v "$binary" >/dev/null 2>&1; then
    log "FAILED: inference binary '$binary' not found; set OLLAMA_BINARY"
    exit 127
fi

log "starting inference service (model: $model)"
"$binary" serve &
serve_pid=$!
trap 'kill "$serve_pid" 2>/dev/null || true' EXIT

ready=0
for _ in $(seq 1 90); do
    if python3 -c "
import urllib.request, sys
try:
    urllib.request.urlopen('http://127.0.0.1:11434/api/version', timeout=2).read()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        ready=1
        break
    fi
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    log "FAILED: inference service did not become ready within 90s"
    exit 1
fi
log "inference service ready"

# Record what is actually running, so a result can be traced to a configuration.
python3 serve/record_service.py --model "$model" --write model/service-measurements.json \
    || log "warning: could not record the service configuration (continuing)"

log "running the agent on $question"
python3 run.py --question "$question" "$@"
status=$?

log "finished with status $status"
exit "$status"
