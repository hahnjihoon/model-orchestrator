import argparse
import hashlib
import json
import os
import random
from collections import Counter
from datetime import datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4


parser = argparse.ArgumentParser(description="운영검증 평가 데이터로 Qwen3-0.6B를 QLoRA 학습합니다.")
parser.add_argument("--data", type=Path, default=Path(__file__).with_name("train.jsonl"))
parser.add_argument("--model", type=Path, default=Path.home() / "aiq-llm/models/qwen3-0.6b")
parser.add_argument("--output-dir", type=Path, default=Path.home() / "aiq-train/output/eval-qlora")
parser.add_argument("--epochs", type=int, default=1)
parser.add_argument("--max-length", type=int, default=2048)
parser.add_argument("--validation-ratio", type=float, default=0.05)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--resume-from-checkpoint", type=Path)
parser.add_argument("--check-data", action="store_true")
args = parser.parse_args()
if args.epochs < 1 or args.max_length < 32 or not 0 < args.validation_ratio < 1:
    parser.error("epochs는 1 이상, max-length는 32 이상, validation-ratio는 0과 1 사이여야 합니다.")
data_path = args.data.expanduser().resolve()
model_path = args.model.expanduser().resolve()
output_path = args.output_dir.expanduser().resolve()
if not data_path.is_file() or not data_path.stat().st_size:
    raise SystemExit(f"학습 데이터 파일이 없거나 비어 있습니다: {data_path}")
if not (model_path / "config.json").is_file():
    raise SystemExit(f"원본 모델을 찾을 수 없습니다: {model_path}")
model_config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
if args.max_length > model_config.get("max_position_embeddings", 32768):
    raise SystemExit("max-length가 원본 모델의 문맥 한도를 초과합니다.")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=False)
if tokenizer.eos_token is None:
    raise SystemExit("원본 모델에 EOS 토큰이 없습니다.")
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"
rows = []
stats = Counter()
data_hash = hashlib.sha256()
with data_path.open(encoding="utf-8") as source:
    for line_number, line in enumerate(source, 1):
        data_hash.update(line.encode("utf-8"))
        if not line.strip():
            continue
        try:
            sample = json.loads(line)
            messages = sample["messages"]
            if not isinstance(messages, list) or len(messages) < 2 or messages[-1].get("role") != "assistant":
                raise ValueError("마지막 메시지는 assistant의 평가 정답이어야 합니다.")
            if not any(message.get("role") == "user" for message in messages[:-1]):
                raise ValueError("질문·답변 입력 메시지가 없습니다.")
            for message in messages:
                if message.get("role") not in ("system", "user", "assistant") or not isinstance(message.get("content"), str):
                    raise ValueError("메시지의 role 또는 content 형식이 잘못되었습니다.")
            scores = json.loads(messages[-1]["content"])
            if not isinstance(scores, list) or len(scores) != 7 or any(value is not None and (type(value) is not int or not 0 <= value <= 4) for value in scores):
                raise ValueError("평가 정답은 0~4 또는 null인 점수 7개 배열이어야 합니다.")
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SystemExit(f"학습 데이터 {line_number}번째 줄 오류: {exc}") from exc
        prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        completion = json.dumps(scores, separators=(",", ":")) + tokenizer.eos_token
        token_count = len(tokenizer(prompt + completion, add_special_tokens=False, return_attention_mask=False)["input_ids"])
        stats["source_rows"] += 1
        if token_count > args.max_length:
            stats["excluded_too_long"] += 1
        else:
            group = sample.get("source", {}).get("split_group") or hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            rows.append({"prompt": prompt, "completion": completion, "group": group})
            stats["usable_rows"] += 1
        if stats["source_rows"] % 5000 == 0:
            print("학습 데이터 확인 단계 :: ", dict(stats))
groups = sorted({row["group"] for row in rows})
if len(groups) < 2:
    raise SystemExit("학습·검증 데이터를 분리할 수 있도록 서로 다른 질문 그룹이 2개 이상 필요합니다.")
random.Random(args.seed).shuffle(groups)
validation_count = min(len(groups) - 1, max(1, round(len(groups) * args.validation_ratio)))
validation_groups = set(groups[:validation_count])
train_rows = []
validation_rows = []
for row in rows:
    destination = validation_rows if row["group"] in validation_groups else train_rows
    destination.append({"prompt": row["prompt"], "completion": row["completion"]})
summary = {
    "data": str(data_path), "data_sha256": data_hash.hexdigest(), "model": str(model_path),
    "output_dir": str(output_path), "epochs": args.epochs, "max_length": args.max_length,
    "seed": args.seed, "stats": dict(stats), "train_rows": len(train_rows),
    "validation_rows": len(validation_rows), "question_groups": len(groups),
    "validation_groups": validation_count, "method": "QLoRA NF4 4bit, LoRA r=16",
}
print("학습 데이터 준비 완료 단계 :: ", summary)
if args.check_data:
    print("데이터 확인 종료 단계 :: ", {"training_started": False})
    raise SystemExit(0)
adapter_exists = (output_path / "adapter_config.json").is_file() and (
    (output_path / "adapter_model.safetensors").is_file() or (output_path / "adapter_model.bin").is_file()
)
if output_path.exists() and any(output_path.iterdir()) and not adapter_exists and args.resume_from_checkpoint is None:
    raise SystemExit("결과 폴더가 비어 있지 않습니다. 다른 --output-dir 또는 --resume-from-checkpoint를 지정하세요.")
import torch
from datasets import Dataset
from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

if not torch.cuda.is_available():
    raise SystemExit("학습용 Python에서 CUDA GPU를 사용할 수 없습니다.")
free_memory, total_memory = torch.cuda.mem_get_info()
if free_memory < 4 * 1024 ** 3:
    raise SystemExit("학습용 GPU 메모리가 부족합니다. 기존 추론 모델을 종료한 뒤 다시 실행하세요.")
compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
print("학습 모델 준비 단계 :: ", {"gpu": torch.cuda.get_device_name(0), "free_gib": round(free_memory / 1024 ** 3, 2)})
quantization = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
    bnb_4bit_compute_dtype=compute_dtype,
)
model = AutoModelForCausalLM.from_pretrained(
    str(model_path), dtype=compute_dtype, quantization_config=quantization,
    device_map={"": 0}, attn_implementation="sdpa", local_files_only=True, trust_remote_code=False,
)
model.config.use_cache = False
model = prepare_model_for_kbit_training(model)
if adapter_exists and args.resume_from_checkpoint is None:
    model = PeftModel.from_pretrained(model, str(output_path), is_trainable=True, local_files_only=True)
    print("기존 학습 가중치 불러오기 단계 :: ", {"path": str(output_path)})
else:
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM", target_modules="all-linear",
    ))
trainable, total = model.get_nb_trainable_parameters()
print("학습 파라미터 확인 단계 :: ", {"trainable": trainable, "total": total})
checkpoint_path = (
    args.resume_from_checkpoint.expanduser().resolve().parent
    if args.resume_from_checkpoint
    else output_path / "checkpoints" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8])
)
config = SFTConfig(
    output_dir=str(checkpoint_path), num_train_epochs=args.epochs,
    per_device_train_batch_size=1, per_device_eval_batch_size=1, gradient_accumulation_steps=8,
    learning_rate=1e-4, lr_scheduler_type="cosine", warmup_ratio=0.03,
    bf16=compute_dtype == torch.bfloat16, fp16=compute_dtype == torch.float16,
    activation_checkpointing=True, optim="adamw_torch", logging_steps=10,
    eval_strategy="epoch", save_strategy="steps", save_steps=100, save_total_limit=2,
    max_length=None, packing=False, completion_only_loss=True,
    report_to="none", dataloader_num_workers=0, seed=args.seed, data_seed=args.seed,
)
trainer = SFTTrainer(
    model=model, args=config, train_dataset=Dataset.from_list(train_rows),
    eval_dataset=Dataset.from_list(validation_rows), processing_class=tokenizer,
)
output_path.mkdir(parents=True, exist_ok=True)
(output_path / "dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
started = perf_counter()
print("학습 시작 단계 :: ", {"epochs": args.epochs, "train_rows": len(train_rows), "validation_rows": len(validation_rows)})
result = trainer.train(resume_from_checkpoint=str(args.resume_from_checkpoint.expanduser().resolve()) if args.resume_from_checkpoint else None)
trainer.save_model(str(output_path))
tokenizer.save_pretrained(str(output_path))
trainer.save_state()
summary["training_metrics"] = result.metrics
summary["log_history"] = trainer.state.log_history
summary["elapsed_seconds"] = round(perf_counter() - started, 3)
summary["training_completed"] = True
(output_path / "training_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("학습 완료 단계 :: ", {"output_dir": str(output_path), "elapsed_seconds": summary["elapsed_seconds"]})
