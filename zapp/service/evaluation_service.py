from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

import httpx


EVALUATION_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "eval_system_deploy.txt").read_text(encoding="utf-8")


async def evaluate(client: httpx.AsyncClient, vllm_base_url: str, model_name: str, question: str, answer: str) -> dict:
    started_at = datetime.now(timezone(timedelta(hours=9)))
    started_counter = perf_counter()
    messages = [
        {"role": "system", "content": EVALUATION_SYSTEM_PROMPT},
        {"role": "user", "content": f"[사용자 질문]\n{question}\n\n[평가할 답변]\n{answer}"},
    ]
    print("모델 질문 전송 단계 :: ", {"model": model_name, "max_tokens": 768})
    response = await client.post(
        f"{vllm_base_url}/chat/completions",
        json={
            "model": model_name,
            "messages": messages,
            "max_tokens": 768,
            "temperature": 0,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    response.raise_for_status()
    result = response.json()
    choice = result["choices"][0]
    message = choice["message"]
    print("모델 응답 수신 단계 :: ", result.get("usage"))
    return {
        "model": result.get("model", model_name),
        "answer": message.get("content") or "",
        "reasoning": message.get("reasoning") or message.get("reasoning_content"),
        "finish_reason": choice.get("finish_reason"),
        "usage": result.get("usage"),
        "started_at": started_at,
        "ended_at": datetime.now(timezone(timedelta(hours=9))),
        "elapsed_seconds": round(perf_counter() - started_counter, 3),
    }
