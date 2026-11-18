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
                "question": "갤럭시 폰, 태블릿, 노트북, TV를 오가며 버즈 사용할 수 있어?",
                "answer": (
                    "**네, 갤럭시 폰·태블릿·갤럭시 북·TV를 오가며 같은 갤럭시 버즈를 연결해 쓸 수 있어요.** 다만 ‘자동으로 기기 전환’까지 원하시는지에 따라 확인 포인트가 달라요.\n"
                    "\n"
                    "🔍 **지금 질문에서 바로 정리되는 핵심**\n"
                    "\n"
                    "**기기마다 블루투스로 개별 연결**해서 쓰는 것은 가능해요. 폰/태블릿/노트북/TV 각각에서 버즈를 블루투스로 페어링해두고, 듣고 싶은 기기에서 연결을 바꿔 쓰는 방식입니다.\n"
                    "**자동 전환**은 기기 조합(특히 TV/노트북 모델과 버즈 모델)에 따라 지원 여부가 달라서, 쓰시는 **버즈 모델명**과 **TV/갤럭시 북 모델명**을 확인해야 정확히 안내할 수 있어요.\n"
                    "\n"
                    "🧭 **구매·세팅 관점에서 중요한 선택 포인트 2가지**\n"
                    "\n"
                    "**TV에서의 사용 방식**: 삼성 TV는 블루투스 헤드셋 연결을 지원하는 모델이 많지만, 일부 모델/환경에서는 원하는 기능(예: 멀티포인트처럼 즉시 전환, 지연 체감 등)이 다를 수 있어요. TV 모델을 알면 “가능/불가”와 연결 경로를 정확히 좁혀드릴 수 있어요.\n"
                    "**버즈를 어떤 방식으로 오가고 싶으신지**:\n"
                    "“필요할 때 수동으로 기기 선택만 하면 된다”면 대부분 문제 없이 쓰는 편이고,\n"
                    "“통화는 폰, 영상은 탭/북/TV로 자동으로 착착 넘어가게”가 목표라면 지원 조합 확인이 핵심이에요.\n"
                    "\n"
                    "먼저 사용 중이신(또는 구매 예정인) **버즈 모델명**과 **TV 모델명**(예: OLED/QLED 연식 또는 모델코드)을 알려주시면, 그 조합에서 ‘자동 전환’까지 가능한지 기준으로 딱 맞게 정리해 드릴게요."
                ),
            }
        }
    }

    question: str = Field(
        min_length=1, description="평가 기준이 되는 사용자 질문입니다.",
        json_schema_extra={
            "format": "multiline",
            "default": model_config["json_schema_extra"]["example"]["question"],
        },
    )
    answer: str = Field(
        min_length=1, description="LLM이 평가할 답변입니다.",
        json_schema_extra={
            "format": "multiline",
            "default": model_config["json_schema_extra"]["example"]["answer"],
        },
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
