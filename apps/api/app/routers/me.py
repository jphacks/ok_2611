"""API 10〜12・14〜17（P1）。アカウント用トークンの本人だけを操作する。

対象アカウントは常に検証済みの `sub`。本人設定はそれぞれ専用RPCの1回の呼び出しで全件置換し、
メニュー・回答には複製しない。本人履歴は `account_id = sub` で絞る。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from supabase import Client

from app.config import Settings, get_settings
from app.dependencies import no_store, require_account
from app.errors import ApiError
from app.schemas.accounts import (
    Account,
    AllergenIds,
    DietaryRestrictionIds,
    HistoryQuery,
    HistoryResponse,
    MenuDetailResponse,
)
from app.schemas.common import VALIDATION_ERROR_RESPONSES, ErrorResponse
from app.schemas.menus import MenuQuery
from app.services import auth as auth_service
from app.services import menus as menu_store
from app.services.history import build_history_page, build_menu_detail
from app.services.menu_results import Targets, load_masters, utcnow
from app.services.supabase_client import get_supabase_client
from app.services.target_ids import check_ids, parse_query_ids

router = APIRouter(
    tags=["P1"],
    responses={
        **VALIDATION_ERROR_RESPONSES,
        401: {"model": ErrorResponse, "description": "unauthorized / account_token_expired"},
    },
    dependencies=[Depends(no_store)],
)

AccountId = Annotated[str, Depends(require_account)]
Db = Annotated[Client, Depends(get_supabase_client)]


@router.get("/me", operation_id="get_me", response_model=Account)
def get_me(account_id: AccountId, db: Db) -> Account:
    return Account(**auth_service.get_account(db, account_id))


def _sorted_ids(db: Client, table: str, column: str, account_id: str) -> list[int]:
    rows = db.table(table).select(column).eq("account_id", account_id).order(column).execute().data
    return [row[column] for row in rows]


@router.get("/me/allergens", operation_id="get_my_allergens", response_model=AllergenIds)
def get_my_allergens(account_id: AccountId, db: Db) -> AllergenIds:
    return AllergenIds(allergen_ids=_sorted_ids(db, "account_allergens", "allergen_id", account_id))


@router.put("/me/allergens", operation_id="replace_my_allergens", response_model=AllergenIds)
def replace_my_allergens(body: AllergenIds, account_id: AccountId, db: Db) -> AllergenIds:
    _, _, allergen_names, _ = load_masters(db)
    check_ids(body.allergen_ids, set(allergen_names), "invalid_allergen_ids")
    ids = db.rpc("replace_account_allergens", {"p_account_id": account_id, "p_allergen_ids": body.allergen_ids})
    return AllergenIds(allergen_ids=sorted(ids.execute().data or []))


@router.get("/me/dietary-restrictions", operation_id="get_my_dietary_restrictions", response_model=DietaryRestrictionIds)
def get_my_dietary_restrictions(account_id: AccountId, db: Db) -> DietaryRestrictionIds:
    return DietaryRestrictionIds(
        dietary_restriction_ids=_sorted_ids(db, "account_dietary_restrictions", "dietary_restriction_id", account_id)
    )


@router.put(
    "/me/dietary-restrictions", operation_id="replace_my_dietary_restrictions", response_model=DietaryRestrictionIds
)
def replace_my_dietary_restrictions(body: DietaryRestrictionIds, account_id: AccountId, db: Db) -> DietaryRestrictionIds:
    _, _, _, dietary_names = load_masters(db)
    check_ids(body.dietary_restriction_ids, set(dietary_names), "invalid_dietary_restriction_ids")
    ids = db.rpc(
        "replace_account_dietary_restrictions",
        {"p_account_id": account_id, "p_dietary_restriction_ids": body.dietary_restriction_ids},
    )
    return DietaryRestrictionIds(dietary_restriction_ids=sorted(ids.execute().data or []))


@router.get("/me/menus", operation_id="get_my_menus", response_model=HistoryResponse)
def list_my_menus(query: Annotated[HistoryQuery, Query()], account_id: AccountId, db: Db) -> HistoryResponse:
    return build_history_page(
        db, account_id, google_place_id=query.google_place_id, cursor=query.cursor, limit=query.limit
    )


@router.get(
    "/me/menus/{menu_id}",
    operation_id="get_my_menu",
    response_model=MenuDetailResponse,
    responses={404: {"model": ErrorResponse, "description": "not_found（他人・ゲスト・存在しないID）"}},
)
def get_my_menu(
    menu_id: uuid.UUID,
    query: Annotated[MenuQuery, Query()],
    request: Request,
    account_id: AccountId,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Db,
) -> MenuDetailResponse:
    menu = menu_store.get_owned_menu(db, str(menu_id), account_id)
    if menu is None:
        raise ApiError(404, "not_found")
    allergen_ids = parse_query_ids(request, "allergen_ids", query.allergen_ids)
    dietary_ids = parse_query_ids(request, "dietary_restriction_ids", query.dietary_restriction_ids)
    _, _, allergen_names, dietary_names = load_masters(db)
    check_ids(allergen_ids, set(allergen_names), "invalid_allergen_ids")
    check_ids(dietary_ids, set(dietary_names), "invalid_dietary_restriction_ids")
    return build_menu_detail(
        db,
        menu,
        targets=Targets(allergen_ids, dietary_ids or []),
        allergen_masters=allergen_names,
        dietary_masters=dietary_names,
        now=utcnow(),
        half_life_days=settings.store_answer_half_life_days,
    )
