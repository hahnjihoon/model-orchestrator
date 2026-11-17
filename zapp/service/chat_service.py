from datetime import datetime, timedelta, timezone
from time import perf_counter

import httpx


async def chat(client: httpx.AsyncClient, vllm_base_url: str, model_name: str, request_data: dict) -> dict:
    started_at = datetime.now(timezone(timedelta(hours=9)))
    started_counter = perf_counter()
    messages = []
    system_prompts = []
    if request_data["system_prompt"].strip():
        system_prompts.append(request_data["system_prompt"])
    for message in request_data["history"]:
        if message["role"] == "system":
            system_prompts.append(message["content"])
        else:
            messages.append(message)
    if system_prompts:
        messages.insert(0, {"role": "system", "content": "\n\n".join(system_prompts)})
    messages.append({"role": "user", "content": request_data["prompt"]})
    model_request = {
        "model": model_name,
        "messages": messages,
        "temperature": request_data["temperature"],
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": request_data["enable_thinking"]},
    }
    if request_data["max_tokens"] is not None:
        model_request["max_tokens"] = request_data["max_tokens"]
    print("모델 질문 전송 단계 :: ", {"model": model_name, "max_tokens": request_data["max_tokens"]})
    response = await client.post(
        f"{vllm_base_url}/chat/completions",
        json=model_request,
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
