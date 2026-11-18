import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

import httpx


EVALUATION_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "eval_system_deploy.txt").read_text(encoding="utf-8")


EVALUATION_METRICS = (
    "accuracy",
    "intent_matching",
    "completeness",
    "clarity_tone",
    "context_awareness",
    "recovery_robustness",
    "safety_compliance",
)


EVALUATION_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        metric: {
            "type": "object",
            "properties": {
                "score": {"anyOf": [{"type": "integer", "minimum": 0, "maximum": 4}, {"type": "null"}]},
                "comment": {"type": "string", "minLength": 1},
            },
            "required": ["score", "comment"],
            "additionalProperties": False,
        }
        for metric in EVALUATION_METRICS
    },
    "required": list(EVALUATION_METRICS),
    "additionalProperties": False,
}


async def evaluate(client: httpx.AsyncClient, vllm_base_url: str, model_name: str, question: str, answer: str) -> dict:
    started_at = datetime.now(timezone(timedelta(hours=9)))
    started_counter = perf_counter()
    messages = [
        {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
        {"role": "user", "content": f"[사용자 질문]\n{question}\n\n[평가할 답변]\n{answer}"},
    ]
    print("모델 질문 전송 단계 :: ", {"model": model_name})
    response = await client.post(
        f"{vllm_base_url}/chat/completions",
        json={
            "model": model_name,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "structured_outputs": {"json": EVALUATION_RESULT_SCHEMA},
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    response.raise_for_status()
    result = response.json()
    choice = result["choices"][0]
    message = choice["message"]
    evaluation = json.loads(message.get("content") or "")
    if not isinstance(evaluation, dict) or set(evaluation) != set(EVALUATION_METRICS):
        raise ValueError("Invalid evaluation metrics")
    for metric in EVALUATION_METRICS:
        metric_result = evaluation[metric]
        if not isinstance(metric_result, dict) or set(metric_result) != {"score", "comment"}:
            raise ValueError(f"Invalid evaluation result: {metric}")
        score = metric_result["score"]
        if score is not None and (type(score) is not int or score < 0 or score > 4):
            raise ValueError(f"Invalid evaluation score: {metric}")
        comment = metric_result["comment"]
        if not isinstance(comment, str) or not comment.strip():
            raise ValueError(f"Invalid evaluation comment: {metric}")
        metric_result["comment"] = comment.strip()
    print("모델 응답 수신 단계 :: ", result.get("usage"))
    return {
        "model": result.get("model", model_name),
        "answer": evaluation,
        "reasoning": message.get("reasoning") or message.get("reasoning_content"),
        "finish_reason": choice.get("finish_reason"),
        "usage": result.get("usage"),
        "started_at": started_at,
        "ended_at": datetime.now(timezone(timedelta(hours=9))),
        "elapsed_seconds": round(perf_counter() - started_counter, 3),
    }
