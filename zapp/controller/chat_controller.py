from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from zapp.service import chat_service


router = APIRouter()


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=300)

class ChatRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "prompt": "너는 누구야?",
                "system_prompt": "한국어로 간결하게 답변하세요.",
                "history": [],
                "max_tokens": 20,
                "temperature": 0.7,
                "enable_thinking": False,
            }
        }
    }

    prompt: str = Field(min_length=1, max_length=300, examples=["너는 누구야?"])
    system_prompt: str = Field(default="한국어로 간결하게 답변하세요.", max_length=400)
    history: list[Message] = Field(default_factory=list, max_length=20)
    max_tokens: int = Field(default=20, ge=1, le=20)
    temperature: float = Field(default=0.7, ge=0, le=2)
    enable_thinking: bool = Field(default=False, description="추론 과정 생성 여부입니다. 간단한 확인은 false로 사용하세요.")

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatResponse(BaseModel):
    model: str
    answer: str
    reasoning: str | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    started_at: datetime = Field(description="한국시간(UTC+09:00) 기준 요청 처리 시작 시각입니다.")
    ended_at: datetime = Field(description="한국시간(UTC+09:00) 기준 요청 처리 종료 시각입니다.")
    elapsed_seconds: float = Field(ge=0, description="요청 처리에 걸린 시간이며 단위는 초입니다.")


@router.post("/chat", response_model=ChatResponse, summary="기본 API")
async def chat(request: ChatRequest, http_request: Request):
    try:
        result = await chat_service.chat(
            client=http_request.app.state.client,
            vllm_base_url=http_request.app.state.vllm_base_url,
            model_name=http_request.app.state.model_name,
            request_data=request.model_dump(),
        )
        return ChatResponse(**result)
    except chat_service.InputLimitExceededError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.ConnectTimeout as exc:
        raise HTTPException(status_code=503, detail="모델 서버 연결 시간이 초과되었습니다. 모델 주소와 네트워크 연결을 확인하세요.") from exc
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="모델이 준비되지 않았습니다. GET /health와 runtime/vllm.log를 확인하세요.") from exc
    except (httpx.ReadTimeout, TimeoutError) as exc:
        raise HTTPException(status_code=504, detail="모델 연결 후 응답 대기 시간이 초과되었습니다. runtime/vllm.log를 확인하세요.") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="모델과 통신 중 대기 시간이 초과되었습니다. runtime/vllm.log를 확인하세요.") from exc
    except httpx.HTTPStatusError as exc:
        try:
            error = exc.response.json()
            detail = error.get("error", {}).get("message") or error.get("detail") or "모델 요청이 실패했습니다."
        except (ValueError, AttributeError):
            detail = "모델 요청이 실패했습니다. runtime/vllm.log를 확인하세요."
        status_code = exc.response.status_code if exc.response.status_code in (400, 422, 429) else 502
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="모델과 통신 중 오류가 발생했습니다.") from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="모델 응답 형식을 확인할 수 없습니다.") from exc
