import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from zapp.controller import chat_controller, docs_controller, evaluation_controller, health_controller


VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8010/v1").rstrip("/")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.8-27b-fp8")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0), trust_env=False) as client:
        app.state.client = client
        runtime_path = Path(__file__).parent / "runtime" / "device.json"
        app.state.runtime = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path.exists() else None
        yield


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="Qwen 로컬 추론 API",
    description="WSL에 설치한 Qwen 모델에 질문을 전송합니다. 모델 준비 상태는 GET /health에서 확인합니다.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    default_response_class=UTF8JSONResponse,
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
)

app.state.vllm_base_url = VLLM_BASE_URL
app.state.model_name = MODEL_NAME

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(docs_controller.router)
app.include_router(health_controller.router)
app.include_router(chat_controller.router)
app.include_router(evaluation_controller.router)
