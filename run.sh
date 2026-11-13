#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi
export PYTHONUTF8=1
export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1
export VLLM_NO_USAGE_STATS=1
export VLLM_USE_FLASHINFER_SAMPLER=0
export MODEL_PATH="${MODEL_PATH:-$HOME/aiq-llm/models/qwen3.8-27b-fp8}"
VLLM_PYTHON="${VLLM_PYTHON:-$HOME/aiq-llm/.venv/bin/python}"
export -n VLLM_PYTHON
mkdir -p runtime
"$VLLM_PYTHON" -c 'import vllm'
"$VLLM_PYTHON" - <<'PY'
import os
import socket
for port in (int(os.getenv('VLLM_PORT', '8010')),):
    with socket.socket() as connection:
        try:
            connection.bind(('127.0.0.1', port))
        except OSError:
            raise SystemExit(f'Port {port} is already in use.')
PY
"$VLLM_PYTHON" scripts/configure_runtime.py
source runtime/device.env
setsid "$VLLM_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "${MODEL_PATH:?MODEL_PATH is required}" \
    --served-model-name "${MODEL_NAME:-qwen3.8-27b-fp8}" \
    --host 0.0.0.0 \
    --port "${VLLM_PORT:-8010}" \
    --language-model-only \
    --cpu-offload-gb "$CPU_OFFLOAD_GB" \
    --cpu-offload-params mlp \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.90}" \
    --max-model-len "${MAX_MODEL_LEN:-2048}" \
    --max-num-seqs 1 \
    --max-num-batched-tokens 256 \
    --enforce-eager \
    --load-format safetensors \
    --safetensors-load-strategy lazy \
    > runtime/vllm.log 2>&1 &
model_pid=$!
trap 'kill -- -"$model_pid" 2>/dev/null || true; wait "$model_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '%s\n' "$model_pid" > runtime/vllm.pid
printf 'Model API port: %s\n' "${VLLM_PORT:-8010}"
printf 'Model log: %s/runtime/vllm.log\n' "$PWD"
wait "$model_pid"
