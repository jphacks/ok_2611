"""API 4 `POST /menus/analyze`・API 5 `GET /menus/{menu_id}`。

解析：レート制限 → 任意のアカウント認証 → multipartの検証 → 対象IDの検証 → 画像の検証・無害化 →
Place IDの確認 → Gemini → 出力の検証 → 店舗の登録 → Storage保存 → `save_menu_analysis` → 判定。
利用者の選択設定（`allergen_ids`・`dietary_restriction_ids`）は判定の対象選択にだけ使い、Gemini・DB・ログへ渡さない。
"""

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from starlette.exceptions import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from supabase import Client

from app.config import Settings, get_settings
from app.dependencies import AuthorizedMenu, authorized_menu, client_ip, no_store
from app.errors import ApiError
from app.schemas.common import VALIDATION_ERROR_RESPONSES, ErrorResponse
from app.schemas.menus import AnalyzeResponse, MenuQuery, MenuResponse
from app.services import menus as menu_store
from app.services.auth import verify_account_token
from app.services.images import MAX_IMAGE_BYTES, SanitizedImage, sanitize_image
from app.services.menu_analysis import (
    PROMPT_VERSION,
    MenuAnalyzer,
    get_menu_analyzer,
    parse_analysis,
)
from app.services.menu_results import (
    MasterName,
    Targets,
    build_menu_response,
    history_item_ids,
    load_masters,
    utcnow,
)
from app.services.places import PlacesClient, get_optional_places_client, verify_place_exists
from app.services.rate_limit import RateLimiter, RateLimitRule, enforce_rate_limit, get_rate_limiter
from app.services.supabase_client import get_supabase_client
from app.services.target_ids import check_ids, parse_id_list, parse_query_ids
from app.services.tokens import bearer_token, hash_analysis_token, new_analysis_token

logger = logging.getLogger("app.menus")

router = APIRouter(tags=["P0"], responses=VALIDATION_ERROR_RESPONSES)

ANALYZE_RATE_LIMITS = (
    RateLimitRule(name="menus_analyze_ip_minute", limit=5, window_seconds=60),
    RateLimitRule(name="menus_analyze_ip_day", limit=50, window_seconds=86_400),
)
# 画像2 MiBにmultipartの区切り・他のフィールドを加えた上限（Vercelの本文上限4.5MBより小さい）
MAX_REQUEST_BYTES = MAX_IMAGE_BYTES + 64 * 1024
FORM_FIELDS = frozenset({"image", "google_place_id", "allergen_ids", "dietary_restriction_ids", "locale"})

_ERRORS = {
    401: {"model": ErrorResponse, "description": "unauthorized / invalid_analysis_token / account_token_expired"},
    404: {"model": ErrorResponse, "description": "not_found / place_not_found"},
    503: {"model": ErrorResponse, "description": "service_unavailable"},
}

ANALYZE_REQUEST_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["image"],
                    "properties": {
                        "image": {"type": "string", "format": "binary"},
                        "google_place_id": {"type": "string", "minLength": 1, "maxLength": 255},
                        "allergen_ids": {"type": "array", "items": {"type": "integer"}, "uniqueItems": True},
                        "dietary_restriction_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "uniqueItems": True,
                        },
                        "locale": {"type": "string", "enum": ["en"], "default": "en"},
                    },
                },
                "encoding": {
                    "allergen_ids": {"style": "form", "explode": True},
                    "dietary_restriction_ids": {"style": "form", "explode": True},
                },
            }
        },
    }
}


@dataclass(frozen=True)
class AnalyzeForm:
    image: bytes
    image_type: str | None
    google_place_id: str | None
    allergen_ids: list[int] | None
    dietary_restriction_ids: list[int] | None


def _invalid() -> ApiError:
    return ApiError(422, "validation_error")


async def _read_body(request: Request) -> None:
    """本文を上限付きで読む。超過は413（画像の容量超過として扱う）。"""
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isdigit():
            raise _invalid()
        if int(length) > MAX_REQUEST_BYTES:
            raise ApiError(413, "image_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise ApiError(413, "image_too_large")
        chunks.append(chunk)
    # 読み終えた本文を form() の解析に使わせる（Starletteは _body があればそれを読む）
    request._body = b"".join(chunks)


def _single_text(values: list) -> str | None:
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], str):
        raise _invalid()
    return values[0]


async def parse_analyze_form(request: Request) -> AnalyzeForm:
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", 1)[0].strip().lower() != "multipart/form-data":
        raise _invalid()
    await _read_body(request)
    try:
        form = await request.form(max_files=1, max_fields=len(FORM_FIELDS) + 40, max_part_size=1024)
    except HTTPException:
        # 区切りの不正・ファイル数／フィールド数／partの長さの超過
        raise _invalid() from None

    keys = set(form.keys())
    if not keys <= FORM_FIELDS:
        # 本文での所有者・利用者同意の指定（account_id・user_publish_consent）などの未定義フィールド
        raise _invalid()
    images = form.getlist("image")
    if len(images) != 1 or not isinstance(images[0], UploadFile):
        raise _invalid()
    for name in keys - {"image"}:
        if any(isinstance(value, UploadFile) for value in form.getlist(name)):
            raise _invalid()

    locale = _single_text(form.getlist("locale"))
    if locale is not None and locale != "en":
        raise _invalid()
    place_id = _single_text(form.getlist("google_place_id"))
    if place_id is not None and not 1 <= len(place_id) <= 255:
        raise _invalid()

    upload: UploadFile = images[0]
    data = await upload.read()
    await form.close()
    return AnalyzeForm(
        image=data,
        image_type=upload.content_type,
        google_place_id=place_id,
        allergen_ids=parse_id_list(form.getlist("allergen_ids")),
        dietary_restriction_ids=parse_id_list(form.getlist("dietary_restriction_ids")),
    )


def _assemble(
    db: Client,
    menu: menu_store.MenuRow,
    targets: Targets,
    allergen_names: dict[int, MasterName],
    dietary_names: dict[int, MasterName],
    settings: Settings,
    *,
    include_menu_answers: bool,
) -> MenuResponse:
    dishes = menu_store.list_dishes(db, menu.id)
    if not dishes:
        raise RuntimeError("menu without dishes")
    menu_allergen, menu_dietary = (
        menu_store.list_menu_answers(db, menu.id) if include_menu_answers else ([], [])
    )
    store_allergen = store_dietary = None
    if menu.restaurant_id is not None:
        name_keys = [dish.name_key for dish in dishes]
        store_allergen = menu_store.list_store_allergen_answers(
            db, menu.restaurant_id, name_keys, history_item_ids(dishes, targets, allergen_names)
        )
        store_dietary = menu_store.list_store_dietary_answers(
            db, menu.restaurant_id, name_keys, targets.dietary_restriction_ids
        )
    return build_menu_response(
        menu=menu,
        dishes=dishes,
        targets=targets,
        allergen_masters=allergen_names,
        dietary_masters=dietary_names,
        menu_allergen_answers=menu_allergen,
        menu_dietary_answers=menu_dietary,
        store_allergen_answers=store_allergen,
        store_dietary_answers=store_dietary,
        now=utcnow(),
        half_life_days=settings.store_answer_half_life_days,
    )


def _analyze(
    form: AnalyzeForm,
    account_token: str | None,
    settings: Settings,
    db: Client,
    places_client: PlacesClient | None,
    analyzer: MenuAnalyzer,
) -> AnalyzeResponse:
    account_id = verify_account_token(account_token, settings, db) if account_token is not None else None

    allergen_items, dietary_items, allergen_names, dietary_names = load_masters(db)
    check_ids(form.allergen_ids, set(allergen_names), "invalid_allergen_ids")
    check_ids(form.dietary_restriction_ids, set(dietary_names), "invalid_dietary_restriction_ids")

    image: SanitizedImage = sanitize_image(form.image, form.image_type)
    if form.google_place_id is not None:
        if places_client is None:
            raise ApiError(503, "service_unavailable")
        verify_place_exists(places_client, form.google_place_id)

    # 選択設定は渡さない。マスタ全件と画像だけ
    raw = analyzer.analyze(image, allergen_items, dietary_items)
    dishes = parse_analysis(raw, set(allergen_names), set(dietary_names))

    restaurant_id = (
        menu_store.get_or_create_restaurant(db, form.google_place_id) if form.google_place_id is not None else None
    )
    token = new_analysis_token()
    image_path = menu_store.new_image_path(image)
    try:
        menu_store.upload_image(db, image_path, image)
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_upload_failed type=%s", type(exc).__name__)
        raise ApiError(503, "service_unavailable") from None
    try:
        menu_id = menu_store.save_menu_analysis(
            db,
            restaurant_id=restaurant_id,
            image_path=image_path,
            token_hash=hash_analysis_token(token),
            dishes=dishes,
            ai_model=analyzer.model,
            prompt_version=PROMPT_VERSION,
            account_id=account_id,
        )
    except Exception:
        menu_store.delete_image(db, image_path)
        raise

    menu = menu_store.get_menu(db, menu_id)
    if menu is None:
        raise RuntimeError("saved menu not found")
    targets = Targets(form.allergen_ids, form.dietary_restriction_ids or [])
    result = _assemble(db, menu, targets, allergen_names, dietary_names, settings, include_menu_answers=False)
    return AnalyzeResponse(**result.model_dump(), analysis_token=token)


@router.post(
    "/menus/analyze",
    operation_id="analyze_menu",
    status_code=201,
    response_model=AnalyzeResponse,
    dependencies=[Depends(no_store)],
    openapi_extra=ANALYZE_REQUEST_BODY,
    responses={
        **_ERRORS,
        413: {"model": ErrorResponse, "description": "image_too_large（容量・画素数の超過）"},
        415: {"model": ErrorResponse, "description": "unsupported_image_type"},
        429: {"model": ErrorResponse, "description": "rate_limited"},
        502: {"model": ErrorResponse, "description": "invalid_ai_output"},
        504: {"model": ErrorResponse, "description": "timeout"},
    },
)
async def analyze_menu(
    request: Request,
    ip: Annotated[str, Depends(client_ip)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Client, Depends(get_supabase_client)],
    places_client: Annotated[PlacesClient | None, Depends(get_optional_places_client)],
    analyzer: Annotated[MenuAnalyzer, Depends(get_menu_analyzer)],
) -> AnalyzeResponse:
    for rule in ANALYZE_RATE_LIMITS:
        await run_in_threadpool(enforce_rate_limit, limiter, rule, ip)
    account_token = bearer_token(request)
    form = await parse_analyze_form(request)
    return await run_in_threadpool(_analyze, form, account_token, settings, db, places_client, analyzer)


@router.get(
    "/menus/{menu_id}",
    operation_id="get_menu",
    response_model=MenuResponse,
    dependencies=[Depends(no_store)],
    responses={**_ERRORS, 410: {"model": ErrorResponse, "description": "analysis_expired"}},
)
def get_menu(
    access: Annotated[AuthorizedMenu, Depends(authorized_menu)],
    query: Annotated[MenuQuery, Query()],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Client, Depends(get_supabase_client)],
) -> MenuResponse:
    allergen_ids = parse_query_ids(request, "allergen_ids", query.allergen_ids)
    dietary_ids = parse_query_ids(request, "dietary_restriction_ids", query.dietary_restriction_ids)
    _, _, allergen_names, dietary_names = load_masters(db)
    check_ids(allergen_ids, set(allergen_names), "invalid_allergen_ids")
    check_ids(dietary_ids, set(dietary_names), "invalid_dietary_restriction_ids")
    targets = Targets(allergen_ids, dietary_ids or [])
    return _assemble(db, access.menu, targets, allergen_names, dietary_names, settings, include_menu_answers=True)
