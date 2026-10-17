"""API 6 `POST /menus/{menu_id}/confirmations`。

解析用トークンの確認（依存）→ 本文の検証 → `complete_confirmation_session` を1回 → 公開判定・結果。
利用者同意は解析時に保存した `menus.user_publish_consent` を読み、本文では受け付けない。
初回は201、同じ `request_id`・同じ内容の再送は200（`replayed=true`）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from supabase import Client

from app.config import Settings, get_settings
from app.dependencies import AuthorizedMenu, authorized_menu, no_store
from app.schemas.common import VALIDATION_ERROR_RESPONSES, ErrorResponse
from app.schemas.confirmations import ConfirmationRequest, ConfirmationResponse
from app.services import menus as menu_store
from app.services.confirmations import build_results, is_public, validate_answers
from app.services.menu_results import load_masters, utcnow
from app.services.supabase_client import get_supabase_client
from app.services.tokens import hash_analysis_token

router = APIRouter(tags=["P0"], responses=VALIDATION_ERROR_RESPONSES)


@router.post(
    "/menus/{menu_id}/confirmations",
    operation_id="create_confirmation",
    status_code=201,
    response_model=ConfirmationResponse,
    dependencies=[Depends(no_store)],
    responses={
        200: {"model": ConfirmationResponse, "description": "同じ request_id・同じ内容の再送（replayed=true）"},
        401: {"model": ErrorResponse, "description": "unauthorized / invalid_analysis_token"},
        404: {"model": ErrorResponse, "description": "not_found"},
        409: {"model": ErrorResponse, "description": "request_id_conflict"},
        410: {"model": ErrorResponse, "description": "analysis_expired"},
    },
)
def create_confirmation(
    access: Annotated[AuthorizedMenu, Depends(authorized_menu)],
    body: ConfirmationRequest,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Client, Depends(get_supabase_client)],
) -> ConfirmationResponse:
    menu = access.menu
    _, _, allergen_names, dietary_names = load_masters(db)
    dishes = menu_store.list_dishes(db, menu.id)
    answers = validate_answers(
        body.answers,
        body.dietary_answers,
        allergen_ids=set(allergen_names),
        dietary_restriction_ids=set(dietary_names),
        menu_dish_ids={dish.id for dish in dishes},
    )

    saved = menu_store.complete_confirmation(
        db,
        menu_id=menu.id,
        token_hash=hash_analysis_token(access.token),
        request_id=str(body.request_id),
        answers=answers.rpc_answers(),
        dietary_answers=answers.rpc_dietary_answers(),
        publish_consent=body.publish_consent,
    )
    if saved.replayed:
        response.status_code = 200

    # 保存後に読むため、今回の回答も同じ店舗の履歴に含まれる（03と同じ扱い）
    store_allergen = store_dietary = None
    if menu.restaurant_id is not None:
        answered = [dish for dish in dishes if dish.id in answers.dish_ids]
        name_keys = [dish.name_key for dish in answered]
        store_allergen = menu_store.list_store_allergen_answers(
            db, menu.restaurant_id, name_keys, sorted({a.item_id for a in answers.allergens})
        )
        store_dietary = menu_store.list_store_dietary_answers(
            db, menu.restaurant_id, name_keys, sorted({a.item_id for a in answers.dietary})
        )

    return ConfirmationResponse(
        session_id=saved.session_id,
        confirmed_at=saved.confirmed_at,
        publish_consent=body.publish_consent,
        user_publish_consent=menu.user_publish_consent,
        is_public=is_public(
            restaurant_id=menu.restaurant_id,
            user_publish_consent=menu.user_publish_consent,
            publish_consent=body.publish_consent,
        ),
        replayed=saved.replayed,
        results=build_results(
            dishes=dishes,
            answers=answers,
            confirmed_at=saved.confirmed_at,
            allergen_masters=allergen_names,
            dietary_masters=dietary_names,
            store_allergen_answers=store_allergen,
            store_dietary_answers=store_dietary,
            now=utcnow(),
            half_life_days=settings.store_answer_half_life_days,
        ),
    )
