#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
if [[ -f .env ]]; then
    set -a
    source <(sed 's/\r$//' .env)
    set +a
fi
export PYTHONUTF8=1
export PYTHONUNBUFFERED=1
export HF_HUB_OFFLINE=1
export VLLM_NO_USAGE_STATS=1
export VLLM_USE_FLASHINFER_SAMPLER=0
export MODEL_PATH="${QWEN_SMALL_MODEL_PATH:-$HOME/aiq-llm/models/qwen3-0.6b}"
export MODEL_NAME="${QWEN_SMALL_MODEL_NAME:-qwen3-0.6b}"
export VLLM_PORT="${QWEN_SMALL_VLLM_PORT:-8010}"
export DEVICE_MODE="${QWEN_SMALL_DEVICE_MODE:-gpu}"
export CPU_OFFLOAD_GB="${QWEN_SMALL_CPU_OFFLOAD_GB:-0}"
export GPU_RESERVE_GB="${QWEN_SMALL_GPU_RESERVE_GB:-1.0}"
export MAX_MODEL_LEN="${QWEN_SMALL_MAX_MODEL_LEN:-2048}"
export GPU_MEMORY_UTILIZATION="${QWEN_SMALL_GPU_MEMORY_UTILIZATION:-0.50}"
VLLM_PYTHON="${QWEN_SMALL_VLLM_PYTHON:-$HOME/aiq-llm/.venv/bin/python}"
export -n VLLM_PYTHON
base_model_name="$MODEL_NAME"
adapter_path="$HOME/aiq-train/output/eval-qlora"
launch_mode="${1:-auto}"
lora_args=()
if [[ ! -x "$VLLM_PYTHON" ]]; then
    printf 'Qwen3-0.6B Python executable was not found: %s\n' "$VLLM_PYTHON" >&2
    exit 1
fi
if [[ ! -f "$MODEL_PATH/config.json" ]]; then
    printf 'Qwen3-0.6B model files were not found: %s. Complete the model download first.\n' "$MODEL_PATH" >&2
    exit 1
fi
if [[ "$launch_mode" == auto ]]; then
    launch_mode=base
    if [[ -f "$adapter_path/adapter_model.safetensors" || -f "$adapter_path/adapter_model.bin" ]]; then
        launch_mode=trained
    fi
fi
if [[ "$launch_mode" == trained ]]; then
    if [[ ! -f "$adapter_path/adapter_config.json" || ( ! -f "$adapter_path/adapter_model.safetensors" && ! -f "$adapter_path/adapter_model.bin" ) ]]; then
        printf 'Trained adapter files are incomplete: %s\n' "$adapter_path" >&2
        exit 1
    fi
    export MODEL_NAME="${base_model_name}-trained"
    lora_args=(--enable-lora --max-lora-rank 16 --lora-modules "$MODEL_NAME=$adapter_path")
elif [[ "$launch_mode" != base ]]; then
    printf 'Invalid model launch mode: %s\n' "$launch_mode" >&2
    exit 1
fi
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
"$VLLM_PYTHON" scripts/configure_runtime3.py
source runtime/device.env
setsid "$VLLM_PYTHON" -m vllm.entrypoints.openai.api_server \
    --model "${MODEL_PATH:?MODEL_PATH is required}" \
    --served-model-name "$base_model_name" \
    "${lora_args[@]}" \
    --host 0.0.0.0 \
    --port "${VLLM_PORT:-8010}" \
    --language-model-only \
    --cpu-offload-gb "$CPU_OFFLOAD_GB" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION:-0.50}" \
    --max-model-len "${MAX_MODEL_LEN:-2048}" \
    --max-num-seqs 1 \
    --max-num-batched-tokens 2048 \
    --enforce-eager \
    --load-format safetensors \
    --safetensors-load-strategy lazy \
    > runtime/vllm3.log 2>&1 &
model_pid=$!
trap 'kill -- -"$model_pid" 2>/dev/null || true; wait "$model_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '%s\n' "$model_pid" > runtime/vllm3.pid
printf 'Model API port: %s\n' "${VLLM_PORT:-8010}"
printf 'Model log: %s/runtime/vllm3.log\n' "$PWD"
wait "$model_pid"
