from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas.common import VALIDATION_ERROR_RESPONSES, NoQuery
from app.schemas.health import HealthResponse

router = APIRouter(tags=["P0"], responses=VALIDATION_ERROR_RESPONSES)


@router.get("/health", operation_id="get_health", response_model=HealthResponse)
def get_health(query: Annotated[NoQuery, Query()]) -> HealthResponse:
    # DB・外部サービスの接続先やバージョンは返さない
    return HealthResponse(status="ok")
