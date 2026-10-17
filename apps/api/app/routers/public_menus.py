"""API 7 `GET /places/{google_place_id}/public-menus`（P1）。

公開ビューだけを読み、店舗・料理名キーごとの公開回答の集計を返す。認証なし。応答は `no-store`。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from supabase import Client

from app.config import Settings, get_settings
from app.dependencies import no_store
from app.schemas.common import VALIDATION_ERROR_RESPONSES
from app.schemas.public_menus import PublicMenusQuery, PublicMenusResponse
from app.services.menu_results import load_masters, utcnow
from app.services.public_menus import build_public_menus
from app.services.supabase_client import get_supabase_client
from app.services.target_ids import check_ids, parse_query_ids

router = APIRouter(tags=["P1"], responses=VALIDATION_ERROR_RESPONSES)


@router.get(
    "/places/{google_place_id}/public-menus",
    operation_id="get_public_menus",
    response_model=PublicMenusResponse,
    dependencies=[Depends(no_store)],
)
def get_public_menus(
    google_place_id: Annotated[str, Path(min_length=1, max_length=255)],
    query: Annotated[PublicMenusQuery, Query()],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Client, Depends(get_supabase_client)],
) -> PublicMenusResponse:
    allergen_ids = parse_query_ids(request, "allergen_ids", query.allergen_ids)
    dietary_ids = parse_query_ids(request, "dietary_restriction_ids", query.dietary_restriction_ids)
    _, _, allergen_names, dietary_names = load_masters(db)
    check_ids(allergen_ids, set(allergen_names), "invalid_allergen_ids")
    check_ids(dietary_ids, set(dietary_names), "invalid_dietary_restriction_ids")
    return build_public_menus(
        db,
        google_place_id=google_place_id,
        allergen_ids=allergen_ids,
        dietary_restriction_ids=dietary_ids or [],
        allergen_masters=allergen_names,
        dietary_masters=dietary_names,
        now=utcnow(),
        half_life_days=settings.store_answer_half_life_days,
    )
