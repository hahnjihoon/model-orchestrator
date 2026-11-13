import json
from datetime import datetime
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError

from zapp.service import evaluation_service


router = APIRouter()


class EvaluationRequest(BaseModel):
    model_config = {
        "json_schema_extra": {
            "example": {
                "question": "비밀번호를 재설정하려면 어떻게 하나요?",
                "answer": "로그인 화면에서 비밀번호 찾기를 선택해 재설정하세요.",
            }
        }
    }

    question: str = Field(
        min_length=1, max_length=4000, description="평가 기준이 되는 사용자 질문입니다.",
        json_schema_extra={"format": "multiline"},
    )
    answer: str = Field(
        min_length=1, max_length=7000, description="LLM이 평가할 답변입니다.",
        json_schema_extra={"format": "multiline"},
    )

class EvaluationTokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class EvaluationResponse(BaseModel):
    model: str
    answer: str
    reasoning: str | None = None
    finish_reason: str | None = None
    usage: EvaluationTokenUsage | None = None
    started_at: datetime = Field(description="한국시간(UTC+09:00) 기준 요청 처리 시작 시각입니다.")
    ended_at: datetime = Field(description="한국시간(UTC+09:00) 기준 요청 처리 종료 시각입니다.")
    elapsed_seconds: float = Field(ge=0, description="요청 처리에 걸린 시간이며 단위는 초입니다.")


@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    summary="평가용 API",
    description="question과 answer 입력칸에 여러 줄 텍스트를 그대로 붙여넣어 평가합니다. 평가 결과는 응답의 answer에 반환됩니다.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {"schema": EvaluationRequest.model_json_schema()},
                "application/json": {
                    "schema": EvaluationRequest.model_json_schema(),
                    "examples": {
                        "evaluation": {"value": EvaluationRequest.model_config["json_schema_extra"]["example"]},
                    },
                },
            },
        },
    },
)
async def evaluate(request: Request):
    content_type = request.headers.get("content-type", "application/json").split(";", 1)[0].strip().lower()
    try:
        body = (await request.body()).decode("utf-8")
        if content_type == "application/x-www-form-urlencoded":
            values = parse_qs(body, keep_blank_values=True, encoding="utf-8", errors="strict")
            payload = {key: items[-1] for key, items in values.items()}
        elif content_type == "application/json" or content_type.endswith("+json"):
            payload = json.loads(body, strict=False)
        else:
            raise HTTPException(status_code=415, detail="질문·답변 입력 폼 또는 JSON으로 전송하세요.")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="요청 내용을 읽을 수 없습니다. 질문과 답변을 입력칸에 각각 붙여넣어주세요.") from exc
    try:
        evaluation_request = EvaluationRequest.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()],
            body=payload,
        ) from exc
    try:
        result = await evaluation_service.evaluate(
            client=request.app.state.client,
            vllm_base_url=request.app.state.vllm_base_url,
            model_name=request.app.state.model_name,
            question=evaluation_request.question,
            answer=evaluation_request.answer,
        )
        return EvaluationResponse(**result)
    except httpx.ConnectTimeout as exc:
        raise HTTPException(status_code=503, detail="모델 서버 연결 시간이 초과되었습니다. 모델 주소와 네트워크 연결을 확인하세요.") from exc
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="모델이 준비되지 않았습니다. GET /health와 runtime/vllm.log를 확인하세요.") from exc
    except httpx.ReadTimeout as exc:
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
