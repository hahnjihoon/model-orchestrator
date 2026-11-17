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


class InputLimitExceededError(ValueError):
    pass


async def evaluate(client: httpx.AsyncClient, vllm_base_url: str, model_name: str, question: str, answer: str) -> dict:
    started_at = datetime.now(timezone(timedelta(hours=9)))
    started_counter = perf_counter()
    messages = [
        {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
        {"role": "user", "content": f"[사용자 질문]\n{question}\n\n[평가할 답변]\n{answer}"},
    ]
    token_response = await client.post(
        f"{vllm_base_url.removesuffix('/v1')}/tokenize",
        json={
            "model": model_name,
            "messages": messages,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=httpx.Timeout(5.0, connect=5.0),
    )
    token_response.raise_for_status()
    prompt_tokens = token_response.json()["count"]
    if prompt_tokens > 700:
        raise InputLimitExceededError(
            f"전체 입력은 700토큰까지 가능합니다. 현재 {prompt_tokens}토큰입니다. 입력 내용을 줄여주세요."
        )
    print("모델 질문 전송 단계 :: ", {"model": model_name, "max_tokens": 20})
    response = await client.post(
        f"{vllm_base_url}/chat/completions",
        json={
            "model": model_name,
            "messages": messages,
            "max_tokens": 20,
            "temperature": 0,
            "stream": False,
            "structured_outputs": {"regex": r"\[(?:[0-4]|null)(?:,(?:[0-4]|null)){6}\]"},
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    response.raise_for_status()
    result = response.json()
    choice = result["choices"][0]
    message = choice["message"]
    scores = json.loads(message.get("content") or "")
    if not isinstance(scores, list) or len(scores) != len(EVALUATION_METRICS):
        raise ValueError("Invalid evaluation score count")
    if any(score is not None and (type(score) is not int or score < 0 or score > 4) for score in scores):
        raise ValueError("Invalid evaluation score")
    evaluation = {metric: {"score": score} for metric, score in zip(EVALUATION_METRICS, scores)}
    print("모델 응답 수신 단계 :: ", result.get("usage"))
    return {
        "model": result.get("model", model_name),
        "answer": json.dumps(evaluation, ensure_ascii=False, separators=(",", ":")),
        "reasoning": message.get("reasoning") or message.get("reasoning_content"),
        "finish_reason": choice.get("finish_reason"),
        "usage": result.get("usage"),
        "started_at": started_at,
        "ended_at": datetime.now(timezone(timedelta(hours=9))),
        "elapsed_seconds": round(perf_counter() - started_counter, 3),
    }
