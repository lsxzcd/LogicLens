#!/usr/bin/env bash
# Populate the model directory. Run this ONCE while the network is available.
#
# The evaluation sandbox has no network, so the weights must already be inside
# the image or on a mounted volume when the container starts. serve/start.sh
# refuses to start without them, which turns a silent evaluation-time failure
# into an immediate, obvious one.
#
# Usage:  bash serve/fetch-model.sh [MODEL]
set -euo pipefail

MODEL="${1:-${LOGICLENS_MODEL_NAME:-qwen2.5-coder:1.5b}}"
BINARY="${OLLAMA_BINARY:-ollama}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/models}"

if ! command -v "$BINARY" >/dev/null 2>&1; then
    echo "inference binary not found: $BINARY" >&2
    exit 127
fi

mkdir -p "$OLLAMA_MODELS"
echo "fetching $MODEL into $OLLAMA_MODELS"
echo "this is a multi-GB download and is the only step that needs a network"

"$BINARY" pull "$MODEL"

echo
echo "now available:"
"$BINARY" list

echo
echo "record the configuration for MODEL.md:"
echo "  python3 serve/record_service.py --model $MODEL --write model/service-measurements.json"
