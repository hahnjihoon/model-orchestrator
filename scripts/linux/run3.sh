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
export MODEL_NAME="${QWEN_SMALL_MODEL_NAME:-qwen3-0.6b}"
export VLLM_PORT="${QWEN_SMALL_VLLM_PORT:-8010}"
export API_PORT="${API_PORT:-8011}"
export MODEL_START_TIMEOUT_SECONDS="${QWEN_SMALL_MODEL_START_TIMEOUT_SECONDS:-900}"
model_python="${QWEN_SMALL_VLLM_PYTHON:-$HOME/aiq-llm/.venv/bin/python}"
if [[ ! -x "$model_python" ]]; then
    printf 'Model Python executable was not found: %s\n' "$model_python" >&2
    exit 1
fi
"$model_python" - <<'PY'
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

project_path = Path.cwd()
model_name = os.environ["MODEL_NAME"]
try:
    model_port = int(os.environ["VLLM_PORT"])
    api_port = int(os.environ["API_PORT"])
    startup_timeout = int(os.environ["MODEL_START_TIMEOUT_SECONDS"])
except ValueError:
    raise SystemExit("Invalid ports or model startup timeout in .env.")
if not 1 <= model_port <= 65535 or not 1 <= api_port <= 65535 or model_port == api_port or startup_timeout < 1:
    raise SystemExit("Invalid ports or model startup timeout in .env.")
launch_arguments = ["bash", str(project_path / "scripts/models/run3.sh")]

adapter_path = Path.home() / "aiq-train/output/eval-qlora"
has_adapter = (adapter_path / "adapter_model.safetensors").is_file() or (adapter_path / "adapter_model.bin").is_file()
if has_adapter:
    if not (adapter_path / "adapter_config.json").is_file():
        raise SystemExit(f"Adapter weights exist but adapter_config.json is missing: {adapter_path}")
    model_name += "-trained"
    os.environ["MODEL_NAME"] = model_name
    launch_arguments.append("trained")
    print("학습 가중치 선택 단계 :: ", str(adapter_path), flush=True)
else:
    launch_arguments.append("base")
    print("기본 모델 선택 단계 :: ", model_name, flush=True)

compose = ["docker", "compose", "-f", str(project_path / "compose.yaml"), "-f", str(project_path / "scripts/linux/compose.yaml")]
try:
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True)
except FileNotFoundError:
    raise SystemExit("Docker was not found. Install Docker Engine and Docker Compose first.")
except subprocess.CalledProcessError:
    raise SystemExit("Start Docker Engine and allow this user to access Docker before running this script.")
if subprocess.run(compose + ["config", "--quiet"]).returncode:
    raise SystemExit("Docker Compose configuration is invalid.")
running_api = subprocess.run(compose + ["ps", "--status", "running", "--quiet", "api"], text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
try:
    with socket.create_connection(("127.0.0.1", api_port), timeout=1):
        if not running_api:
            raise SystemExit(f"Port {api_port} is already in use outside this project's Docker API. Stop the old API first.")
except OSError:
    pass

runtime_path = project_path / "runtime"
runtime_path.mkdir(exist_ok=True)
model_url = f"http://127.0.0.1:{model_port}/v1/models"
opener = build_opener(ProxyHandler({}))
launcher = None
launch_checked = False
deadline = time.monotonic() + startup_timeout
while time.monotonic() < deadline:
    model_ready = False
    try:
        with opener.open(model_url, timeout=3) as response:
            payload = json.load(response)
        if model_name not in [entry.get("id") for entry in payload.get("data", [])]:
            raise SystemExit(f"A different service or model is using {model_url}.")
        model_ready = True
    except (URLError, TimeoutError, OSError, ValueError):
        pass
    if model_ready:
        break
    if not launch_checked:
        launch_checked = True
        try:
            with socket.create_connection(("127.0.0.1", model_port), timeout=1):
                model_listening = True
        except OSError:
            model_listening = False
        if model_listening:
            print("기존 모델 준비 대기 단계 :: ", model_url, flush=True)
        else:
            print("모델 서버 실행 단계 :: ", {"port": model_port}, flush=True)
            with (runtime_path / "model3-launcher.log").open("w", encoding="utf-8") as stdout, (runtime_path / "model3-launcher-error.log").open("w", encoding="utf-8") as stderr:
                launcher = subprocess.Popen(launch_arguments, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
    if launcher is not None and launcher.poll() is not None:
        raise SystemExit("The Linux model launcher exited. Check runtime/model3-launcher-error.log and runtime/vllm3.log.")
    time.sleep(2)
else:
    raise SystemExit(f"Model readiness timed out after {startup_timeout} seconds. Check runtime/vllm3.log.")

print("모델 준비 완료 단계 :: ", model_url, flush=True)
result = subprocess.run(compose + ["up", "-d", "--build"])
if result.returncode:
    raise SystemExit(result.returncode)
print("API 실행 완료 단계 :: ", {"swagger": f"http://localhost:{api_port}/docs"}, flush=True)
PY
