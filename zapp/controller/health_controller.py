import httpx
from fastapi import APIRouter, HTTPException, Request

from zapp.service import health_service


router = APIRouter()


@router.get("/health", summary="모델 준비 상태 확인")
async def health(request: Request):
    try:
        result = await health_service.health(
            client=request.app.state.client,
            vllm_base_url=request.app.state.vllm_base_url,
            model_name=request.app.state.model_name,
            runtime=request.app.state.runtime,
        )
        if result is None:
            raise HTTPException(status_code=503, detail="설정된 모델이 준비되지 않았습니다. runtime/vllm.log를 확인하세요.")
        return result
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="모델이 로딩 중이거나 실행되지 않았습니다. runtime/vllm.log를 확인하세요.") from exc
