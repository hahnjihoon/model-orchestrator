import json
import math
import os
import struct
from pathlib import Path

import torch


model_path = Path(os.environ["MODEL_PATH"]).expanduser()
model_config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
if model_config.get("model_type") not in {"gemma4", "gemma4_text"}:
    raise SystemExit(f"The configured model is not Gemma 4: {model_path}")
mode = os.getenv("DEVICE_MODE", "auto").lower()
if mode not in {"auto", "gpu", "hybrid"}:
    raise SystemExit("DEVICE_MODE must be auto, gpu, or hybrid.")
if not torch.cuda.is_available():
    raise SystemExit("CUDA GPU is not available in WSL.")

index_path = model_path / "model.safetensors.index.json"
if index_path.exists():
    index = json.loads(index_path.read_text(encoding="utf-8"))
    model_files = [model_path / name for name in sorted(set(index["weight_map"].values()))]
else:
    model_files = sorted(model_path.glob("*.safetensors"))
if not model_files:
    raise SystemExit(f"No safetensors model files found: {model_path}")

weight_bytes = 0
offloadable_bytes = 0
for model_file in model_files:
    with model_file.open("rb") as source:
        header_size = struct.unpack("<Q", source.read(8))[0]
        header = json.loads(source.read(header_size))
    for name, tensor in header.items():
        if name == "__metadata__" or {"vision_tower", "multi_modal_projector", "audio_tower", "audio_projector", "embed_vision", "embed_audio", "mtp"}.intersection(name.split(".")):
            continue
        weight_bytes += tensor["data_offsets"][1] - tensor["data_offsets"][0]
        if "mlp" in name.split("."):
            offloadable_bytes += tensor["data_offsets"][1] - tensor["data_offsets"][0]

gib = 1024 ** 3
gpu_free, gpu_total = torch.cuda.mem_get_info()
utilization = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.90"))
if not 0 < utilization < 1:
    raise SystemExit("GPU_MEMORY_UTILIZATION must be between 0 and 1.")
runtime_reserve = float(os.getenv("GPU_RESERVE_GB", "1.0"))
if runtime_reserve < 0:
    raise SystemExit("GPU_RESERVE_GB must not be negative.")
utilization = min(utilization, max(0.0, (gpu_free - 0.25 * gib) / gpu_total))
gpu_budget = gpu_total * utilization / gib - runtime_reserve
if gpu_budget <= 0:
    raise SystemExit("Not enough free GPU memory to start the model.")
required_offload = math.ceil(max(0.0, weight_bytes / gib - gpu_budget) * 2) / 2
if mode == "gpu" and required_offload > 0:
    raise SystemExit(f"GPU-only mode needs more VRAM. Estimated CPU offload required: {required_offload} GiB.")

configured_offload = os.getenv("CPU_OFFLOAD_GB", "auto").lower()
offload_gb = required_offload
if mode == "gpu":
    offload_gb = 0.0
elif configured_offload != "auto":
    offload_gb = float(configured_offload)
    if offload_gb < required_offload:
        raise SystemExit(f"CPU_OFFLOAD_GB is too small. Estimated minimum: {required_offload} GiB.")
if mode == "hybrid":
    offload_gb = max(0.5, offload_gb)
if offload_gb > offloadable_bytes / gib:
    raise SystemExit("Not enough GPU memory for this model with MLP-only CPU offloading.")

runtime = {
    "model": os.environ.get("MODEL_NAME", "gemma-4-31b-it-qat-w4a16-ct"),
    "requested_mode": mode,
    "selected_mode": "hybrid" if offload_gb else "gpu",
    "gpu": torch.cuda.get_device_name(0),
    "gpu_total_gib": round(gpu_total / gib, 2),
    "gpu_free_at_start_gib": round(gpu_free / gib, 2),
    "model_weights_gib": round(weight_bytes / gib, 2),
    "cpu_offload_gib": offload_gb,
    "cpu_offload_params": ["mlp"] if offload_gb else [],
    "gpu_reserve_gib": runtime_reserve,
    "gpu_memory_utilization": round(utilization, 4),
}
runtime_path = Path(__file__).resolve().parent.parent / "runtime"
runtime_path.mkdir(exist_ok=True)
(runtime_path / "device.json").write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
(runtime_path / "device.env").write_text(
    f"CPU_OFFLOAD_GB={offload_gb}\nGPU_MEMORY_UTILIZATION={utilization}\n", encoding="utf-8"
)
print("Gemma 실행 장치 선택 단계 :: ", runtime)
