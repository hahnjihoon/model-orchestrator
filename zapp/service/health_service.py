import httpx


async def health(client: httpx.AsyncClient, vllm_base_url: str, model_name: str, runtime: dict | None) -> dict | None:
    response = await client.get(f"{vllm_base_url}/models", timeout=5.0)
    response.raise_for_status()
    models = response.json().get("data", [])
    ready = any(model.get("id") == model_name for model in models)
    if not ready:
        return None
    return {"status": "ready", "model": model_name, "runtime": runtime, "models": [model.get("id") for model in models]}
