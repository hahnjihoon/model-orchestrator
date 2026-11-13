import asyncio
from datetime import datetime, timedelta, timezone
from time import perf_counter

import httpx


class InputLimitExceededError(ValueError):
    pass


async def chat(client: httpx.AsyncClient, vllm_base_url: str, model_name: str, request_data: dict) -> dict:
    started_at = datetime.now(timezone(timedelta(hours=9)))
    started_counter = perf_counter()
    async with asyncio.timeout(90.0):
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
        token_response = await client.post(
            f"{vllm_base_url.removesuffix('/v1')}/tokenize",
            json={
                "model": model_name,
                "messages": messages,
                "chat_template_kwargs": {"enable_thinking": request_data["enable_thinking"]},
            },
            timeout=httpx.Timeout(5.0, connect=5.0),
        )
        token_response.raise_for_status()
        prompt_tokens = token_response.json()["count"]
        if prompt_tokens > 700:
            raise InputLimitExceededError(
                f"전체 입력은 700토큰까지 가능합니다. 현재 {prompt_tokens}토큰입니다. 입력 내용을 줄여주세요."
            )
        print("모델 질문 전송 단계 :: ", {"model": model_name, "max_tokens": request_data["max_tokens"]})
        response = await client.post(
            f"{vllm_base_url}/chat/completions",
            json={
                "model": model_name,
                "messages": messages,
                "max_tokens": request_data["max_tokens"],
                "temperature": request_data["temperature"],
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": request_data["enable_thinking"]},
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
