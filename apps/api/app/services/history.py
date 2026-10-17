"""本人の読み込み履歴（API 16・17）。

- どのクエリにも検証済みの `JWT.sub` を所有者条件として付ける（`app.services.menus.list_history`・
  `get_owned_menu`）。店舗・カーソルの条件はANDで追加する。カーソルはページ位置であり認証の代わりにしない。
- 詳細の判定（AIの候補・今回の回答・履歴の集計）は03と同じ処理を使う。`confirmations` はこのメニューの確認だけ。
- 解析用トークンの期限・画像の有無に関係なく読めるが、読み取り専用（回答の追加・トークンの再発行はしない）。
"""

import base64
import json
import uuid
from datetime import datetime

from supabase import Client

from app.errors import ApiError
from app.schemas.accounts import ConfirmationRecord, HistoryMenu, HistoryResponse, MenuDetailResponse
from app.services import menus as menu_store
from app.services.confirmations import Answer, ValidatedAnswers, build_results, is_public
from app.services.menu_results import MasterName, Targets, build_menu_response, history_item_ids
from app.services.menus import MenuRow


def encode_cursor(created_at: str, menu_id: str) -> str:
    raw = json.dumps({"t": created_at, "id": menu_id}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    """不正なカーソルは422。値は正規化し直してからクエリに使う（文字列をそのまま埋め込まない）。"""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        created_at = datetime.fromisoformat(data["t"])
        menu_id = str(uuid.UUID(data["id"]))
        if created_at.tzinfo is None or set(data) != {"t", "id"}:
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        raise ApiError(422, "validation_error") from None
    return created_at.isoformat(), menu_id


def build_history_page(
    db: Client, account_id: str, *, google_place_id: str | None, cursor: str | None, limit: int
) -> HistoryResponse:
    after = decode_cursor(cursor) if cursor else None
    rows = menu_store.list_history(db, account_id, google_place_id=google_place_id, after=after, limit=limit + 1)
    page, more = rows[:limit], len(rows) > limit
    return HistoryResponse(
        menus=[
            HistoryMenu(
                menu_id=row.menu_id,
                google_place_id=row.google_place_id,
                scanned_at=row.scanned_at,
                dish_names=row.dish_names,
                dish_count=len(row.dish_names),
                confirmation_count=row.confirmation_count,
                is_public=row.is_public,
            )
            for row in page
        ],
        next_cursor=encode_cursor(page[-1].scanned_at_raw, page[-1].menu_id) if more and page else None,
    )


def build_menu_detail(
    db: Client,
    menu: MenuRow,
    *,
    targets: Targets,
    allergen_masters: dict[int, MasterName],
    dietary_masters: dict[int, MasterName],
    now: datetime,
    half_life_days: float,
) -> MenuDetailResponse:
    dishes = menu_store.list_dishes(db, menu.id)
    if not dishes:
        raise RuntimeError("menu without dishes")
    sessions = menu_store.list_menu_sessions(db, menu.id)
    menu_allergen = [a for s in sessions for a in s.allergens]
    menu_dietary = [a for s in sessions for a in s.dietary]

    store_allergen = store_dietary = None
    if menu.restaurant_id is not None:
        name_keys = [dish.name_key for dish in dishes]
        allergen_ids = set(history_item_ids(dishes, targets, allergen_masters)) | {a.item_id for a in menu_allergen}
        dietary_ids = set(targets.dietary_restriction_ids) | {a.item_id for a in menu_dietary}
        store_allergen = menu_store.list_store_allergen_answers(db, menu.restaurant_id, name_keys, sorted(allergen_ids))
        store_dietary = menu_store.list_store_dietary_answers(db, menu.restaurant_id, name_keys, sorted(dietary_ids))

    base = build_menu_response(
        menu=menu,
        dishes=dishes,
        targets=targets,
        allergen_masters=allergen_masters,
        dietary_masters=dietary_masters,
        menu_allergen_answers=menu_allergen,
        menu_dietary_answers=menu_dietary,
        store_allergen_answers=store_allergen,
        store_dietary_answers=store_dietary,
        now=now,
        half_life_days=half_life_days,
    )
    confirmations = []
    for session in sessions:
        answers = ValidatedAnswers(
            [Answer(a.dish_id, a.item_id, a.answer) for a in session.allergens],
            [Answer(a.dish_id, a.item_id, a.answer) for a in session.dietary],
        )
        confirmations.append(
            ConfirmationRecord(
                session_id=session.session_id,
                confirmed_at=session.confirmed_at,
                publish_consent=session.publish_consent,
                is_public=is_public(
                    restaurant_id=menu.restaurant_id,
                    user_publish_consent=menu.user_publish_consent,
                    publish_consent=session.publish_consent,
                ),
                results=build_results(
                    dishes=dishes,
                    answers=answers,
                    confirmed_at=session.confirmed_at,
                    allergen_masters=allergen_masters,
                    dietary_masters=dietary_masters,
                    store_allergen_answers=store_allergen,
                    store_dietary_answers=store_dietary,
                    now=now,
                    half_life_days=half_life_days,
                ),
            )
        )
    return MenuDetailResponse(
        menu_id=base.menu_id,
        google_place_id=base.google_place_id,
        ai_model=base.ai_model,
        prompt_version=base.prompt_version,
        analyzed_at=base.analyzed_at,
        locale=base.locale,
        dishes=base.dishes,
        user_publish_consent=menu.user_publish_consent,
        is_public=any(c.is_public for c in confirmations),
        confirmations=confirmations,
    )
