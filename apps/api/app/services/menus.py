"""メニュー・料理・回答のDB操作とStorage（API 4・5・6）。

- 解析の保存は `save_menu_analysis`、店員確認の保存は `complete_confirmation_session` の各1回のRPCだけで行う。Storageへの保存後にDB登録が失敗したら画像を削除する。
- 画像のパスはランダムに作り、クライアントへ返さない。
- 履歴は同じ店舗（`confirmation_sessions.restaurant_id`）・同じ `name_key` の回答を、公開可否に関係なく読む。
  店舗IDを必ず条件にするため、店舗未選択の回答は含まれない。返すのは集計に必要な値と日時だけ。
- 回答の値はここでAPIの値に変換する（`app.services.answers`）。
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from postgrest.exceptions import APIError
from supabase import Client

from app.services.answers import allergen_answer_from_db, dietary_answer_from_db
from app.services.images import SanitizedImage
from app.services.menu_analysis import AnalyzedDish

logger = logging.getLogger("app.menus")

BUCKET = "menu-images"
PAGE_SIZE = 1000
IN_CHUNK = 100  # in.() に並べる値の数（URLの長さを抑える）


@dataclass(frozen=True)
class MenuRow:
    id: str
    restaurant_id: str | None
    google_place_id: str | None
    analysis_token_hash: str
    analysis_expires_at: datetime
    user_publish_consent: bool = False


@dataclass(frozen=True)
class DishRow:
    id: str
    position: int
    name: str
    name_key: str
    translations: dict
    price: float | int | None
    currency: str
    version: int
    ai_result: dict
    ai_model: str
    prompt_version: str
    analyzed_at: datetime


@dataclass(frozen=True)
class MenuAnswer:
    """このメニューの回答（APIの値）。"""

    dish_id: str
    item_id: int
    answer: str
    confirmed_at: datetime


@dataclass(frozen=True)
class StoreAnswerRow:
    """同じ店舗の回答（APIの値）。"""

    menu_id: str
    name_key: str
    item_id: int
    answer: str
    confirmed_at: datetime


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _price(value) -> float | int | None:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


# --- 保存（API 4） ---


def get_or_create_restaurant(client: Client, google_place_id: str) -> str:
    """Place IDだけを保存する。同時登録の一意制約違反は再取得で処理する。"""
    existing = _find_restaurant(client, google_place_id)
    if existing:
        return existing
    try:
        rows = client.table("restaurants").insert({"google_place_id": google_place_id}).execute().data
        return rows[0]["id"]
    except APIError as exc:
        if exc.code != "23505":
            raise
    existing = _find_restaurant(client, google_place_id)
    if existing is None:
        raise RuntimeError("restaurant not found after unique violation")
    return existing


def _find_restaurant(client: Client, google_place_id: str) -> str | None:
    rows = (
        client.table("restaurants").select("id").eq("google_place_id", google_place_id).limit(1).execute().data
    )
    return rows[0]["id"] if rows else None


def new_image_path(image: SanitizedImage) -> str:
    return f"menus/{uuid.uuid4()}.{image.extension}"


def upload_image(client: Client, path: str, image: SanitizedImage) -> None:
    client.storage.from_(BUCKET).upload(path, image.data, {"content-type": image.content_type, "upsert": "false"})


def delete_image(client: Client, path: str) -> None:
    """DB登録に失敗した画像をStorage APIで削除する。削除の失敗は元のエラーを隠さない。"""
    try:
        client.storage.from_(BUCKET).remove([path])
    except Exception as exc:  # noqa: BLE001
        # パスは記録しない（メニューと結び付けられるため）
        logger.error("image_cleanup_failed type=%s", type(exc).__name__)


def save_menu_analysis(
    client: Client,
    *,
    restaurant_id: str | None,
    image_path: str,
    token_hash: str,
    dishes: list[AnalyzedDish],
    ai_model: str,
    prompt_version: str,
    account_id: str | None,
) -> str:
    params = {
        "p_restaurant_id": restaurant_id,
        "p_image_path": image_path,
        "p_analysis_token_hash": token_hash,
        "p_dishes": [dish.rpc_payload() for dish in dishes],
        "p_ai_model": ai_model,
        "p_prompt_version": prompt_version,
    }
    if account_id is not None:
        params["p_account_id"] = account_id
    return str(client.rpc("save_menu_analysis", params).execute().data)


@dataclass(frozen=True)
class SavedConfirmation:
    session_id: str
    confirmed_at: datetime
    replayed: bool


def complete_confirmation(
    client: Client,
    *,
    menu_id: str,
    token_hash: str,
    request_id: str,
    answers: list[dict],
    dietary_answers: list[dict],
    publish_consent: bool,
) -> SavedConfirmation:
    """`complete_confirmation_session` を1回だけ呼ぶ（API 6）。回答はDBの値で渡す。"""
    row = (
        client.rpc(
            "complete_confirmation_session",
            {
                "p_menu_id": menu_id,
                "p_analysis_token_hash": token_hash,
                "p_request_id": request_id,
                "p_answers": answers,
                "p_dietary_answers": dietary_answers,
                "p_publish_consent": publish_consent,
            },
        )
        .execute()
        .data
    )
    if isinstance(row, list):  # PostgRESTの版によっては1行の配列で返る
        row = row[0]
    return SavedConfirmation(
        session_id=str(row["session_id"]),
        confirmed_at=parse_timestamp(row["confirmed_at"]),
        replayed=bool(row["replayed"]),
    )


# --- 読み取り（API 4・5・6） ---


def get_menu(client: Client, menu_id: str) -> MenuRow | None:
    rows = (
        client.table("menus")
        .select("id,restaurant_id,user_publish_consent,analysis_token_hash,analysis_expires_at,restaurants(google_place_id)")
        .eq("id", menu_id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        return None
    row = rows[0]
    restaurant = row.get("restaurants") or {}
    return MenuRow(
        id=row["id"],
        restaurant_id=row["restaurant_id"],
        google_place_id=restaurant.get("google_place_id"),
        analysis_token_hash=row["analysis_token_hash"],
        analysis_expires_at=parse_timestamp(row["analysis_expires_at"]),
        user_publish_consent=bool(row["user_publish_consent"]),
    )


def list_dishes(client: Client, menu_id: str) -> list[DishRow]:
    rows = (
        client.table("dishes")
        .select(
            "id,position,name,name_key,translations,price,currency,version,ai_result,ai_model,prompt_version,analyzed_at"
        )
        .eq("menu_id", menu_id)
        .order("position")
        .execute()
        .data
    )
    return [
        DishRow(
            id=row["id"],
            position=row["position"],
            name=row["name"],
            name_key=row["name_key"],
            translations=row["translations"],
            price=_price(row["price"]),
            currency=row["currency"],
            version=row["version"],
            ai_result=row["ai_result"],
            ai_model=row["ai_model"],
            prompt_version=row["prompt_version"],
            analyzed_at=parse_timestamp(row["analyzed_at"]),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class MenuSession:
    """このメニューの確認1件（回答はAPIの値）。"""

    session_id: str
    confirmed_at: datetime
    publish_consent: bool
    allergens: list[MenuAnswer]
    dietary: list[MenuAnswer]


def list_menu_sessions(client: Client, menu_id: str) -> list[MenuSession]:
    """このメニューの確認（最大5件）を新しい順（同日時はIDの降順）に返す。"""
    rows = (
        client.table("confirmation_sessions")
        .select(
            "id,created_at,publish_consent,"
            "confirmation_answers(dish_id,allergen_id,answer),"
            "confirmation_dietary_answers(dish_id,dietary_restriction_id,answer)"
        )
        .eq("menu_id", menu_id)
        .execute()
        .data
    )
    sessions = []
    for row in rows:
        confirmed_at = parse_timestamp(row["created_at"])
        sessions.append(
            MenuSession(
                session_id=row["id"],
                confirmed_at=confirmed_at,
                publish_consent=bool(row["publish_consent"]),
                allergens=[
                    MenuAnswer(a["dish_id"], a["allergen_id"], allergen_answer_from_db(a["answer"]), confirmed_at)
                    for a in row.get("confirmation_answers") or []
                ],
                dietary=[
                    MenuAnswer(
                        a["dish_id"], a["dietary_restriction_id"], dietary_answer_from_db(a["answer"]), confirmed_at
                    )
                    for a in row.get("confirmation_dietary_answers") or []
                ],
            )
        )
    return sorted(sessions, key=lambda x: (x.confirmed_at, x.session_id), reverse=True)


def list_menu_answers(client: Client, menu_id: str) -> tuple[list[MenuAnswer], list[MenuAnswer]]:
    """このメニューの確認の回答を、アレルゲン・食事制限に分けて返す。"""
    sessions = list_menu_sessions(client, menu_id)
    return (
        [a for session in sessions for a in session.allergens],
        [a for session in sessions for a in session.dietary],
    )


# --- 本人履歴（API 16・17）。どのクエリにも必ず account_id = 検証済みの sub を付ける ---

_MENU_COLUMNS = "id,restaurant_id,user_publish_consent,analysis_token_hash,analysis_expires_at"


def _menu_row(row: dict) -> MenuRow:
    restaurant = row.get("restaurants") or {}
    return MenuRow(
        id=row["id"],
        restaurant_id=row["restaurant_id"],
        google_place_id=restaurant.get("google_place_id"),
        analysis_token_hash=row["analysis_token_hash"],
        analysis_expires_at=parse_timestamp(row["analysis_expires_at"]),
        user_publish_consent=bool(row["user_publish_consent"]),
    )


def get_owned_menu(client: Client, menu_id: str, account_id: str) -> MenuRow | None:
    """メニューIDと所有者を同じクエリで検証する。他人・ゲスト・存在しないIDは区別しない。"""
    rows = (
        client.table("menus")
        .select(f"{_MENU_COLUMNS},restaurants(google_place_id)")
        .eq("id", menu_id)
        .eq("account_id", account_id)
        .limit(1)
        .execute()
        .data
    )
    return _menu_row(rows[0]) if rows else None


@dataclass(frozen=True)
class HistoryRow:
    menu_id: str
    google_place_id: str | None
    scanned_at: datetime
    scanned_at_raw: str  # カーソル用（DBの値をそのまま使い、精度を落とさない）
    dish_names: list[str]
    confirmation_count: int
    is_public: bool


def list_history(
    client: Client,
    account_id: str,
    *,
    google_place_id: str | None,
    after: tuple[str, str] | None,
    limit: int,
) -> list[HistoryRow]:
    """`created_at DESC, id DESC`。所有者・店舗・カーソルの条件はANDで付ける。"""
    restaurants = "restaurants!inner(google_place_id)" if google_place_id else "restaurants(google_place_id)"
    query = (
        client.table("menus")
        .select(
            f"id,created_at,restaurant_id,user_publish_consent,{restaurants},"
            "dishes(position,translations),confirmation_sessions(publish_consent)"
        )
        .eq("account_id", account_id)
    )
    if google_place_id:
        query = query.eq("restaurants.google_place_id", google_place_id)
    if after:
        created_at, menu_id = after
        query = query.or_(f'created_at.lt."{created_at}",and(created_at.eq."{created_at}",id.lt.{menu_id})')
    rows = query.order("created_at", desc=True).order("id", desc=True).limit(limit).execute().data
    result = []
    for row in rows:
        dishes = sorted(row.get("dishes") or [], key=lambda d: d["position"])
        sessions = row.get("confirmation_sessions") or []
        restaurant = row.get("restaurants") or {}
        result.append(
            HistoryRow(
                menu_id=row["id"],
                google_place_id=restaurant.get("google_place_id"),
                scanned_at=parse_timestamp(row["created_at"]),
                scanned_at_raw=row["created_at"],
                dish_names=[((d.get("translations") or {}).get("en") or {}).get("name", "") for d in dishes],
                confirmation_count=len(sessions),
                is_public=bool(
                    row["user_publish_consent"]
                    and row["restaurant_id"] is not None
                    and any(x["publish_consent"] for x in sessions)
                ),
            )
        )
    return result


def list_store_allergen_answers(
    client: Client, restaurant_id: str, name_keys: list[str], allergen_ids: list[int]
) -> list[StoreAnswerRow]:
    return _store_answers(
        client, "confirmation_answers", "allergen_id", restaurant_id, name_keys, allergen_ids, allergen_answer_from_db
    )


def list_store_dietary_answers(
    client: Client, restaurant_id: str, name_keys: list[str], dietary_restriction_ids: list[int]
) -> list[StoreAnswerRow]:
    return _store_answers(
        client,
        "confirmation_dietary_answers",
        "dietary_restriction_id",
        restaurant_id,
        name_keys,
        dietary_restriction_ids,
        dietary_answer_from_db,
    )


def _store_answers(client, table, id_column, restaurant_id, name_keys, item_ids, convert) -> list[StoreAnswerRow]:
    if not name_keys or not item_ids:
        return []
    keys = sorted(set(name_keys))
    result: list[StoreAnswerRow] = []
    for start in range(0, len(keys), IN_CHUNK):
        chunk = keys[start : start + IN_CHUNK]
        offset = 0
        while True:
            rows = (
                client.table(table)
                .select(f"id,{id_column},answer,confirmation_sessions!inner(menu_id,restaurant_id,created_at),dishes!inner(name_key)")
                .eq("confirmation_sessions.restaurant_id", restaurant_id)
                .in_("dishes.name_key", chunk)
                .in_(id_column, sorted(set(item_ids)))
                .order("id")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
                .data
            )
            for row in rows:
                session, dish = row["confirmation_sessions"], row["dishes"]
                if session["restaurant_id"] != restaurant_id or dish["name_key"] not in chunk:
                    continue  # 条件の取り違えに備えて店舗・料理名キーを再確認する
                result.append(
                    StoreAnswerRow(
                        menu_id=session["menu_id"],
                        name_key=dish["name_key"],
                        item_id=row[id_column],
                        answer=convert(row["answer"]),
                        confirmed_at=parse_timestamp(session["created_at"]),
                    )
                )
            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return result
