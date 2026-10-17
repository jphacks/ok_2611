"""公開メニューの集計（API 7）。

- 読み取り元は公開ビュー `published_menus`・`published_confirmation_answers`・`published_dietary_answers` だけ。
  解析・本人履歴の判定用の取得（非公開回答を含む `app.services.menus` の関数）は使わない。
- 同じ店舗・`name_key` ごとに1料理にまとめる。表示内容とAIの候補は公開対象のうち最新の料理（撮影日時が
  最新、同日時は料理IDの降順）から採る。AIの候補と店員回答は合成しない。
- 公開回答は03と同じ規則（同じメニューは最新の1件、α・β・S、器具共有・不明は件数だけ）で集計する。
- 料理は代表料理の撮影日時の降順、同日時は `name_key` の昇順。
"""

from dataclasses import dataclass
from datetime import datetime

from supabase import Client

from app.schemas.public_menus import (
    PublicAllergenAssessment,
    PublicAllergenNotices,
    PublicDietaryAssessment,
    PublicDietaryNotices,
    PublicDish,
    PublicMenusResponse,
)
from app.services.answers import allergen_answer_from_db, dietary_answer_from_db
from app.services.assessment import ALLERGEN_SCALE, DIETARY_SCALE, UNKNOWN_AI, HistoryAnswer, assess_item
from app.services.menu_results import MasterName, ai_candidates, allergen_parts, allergen_target_ids, dietary_parts
from app.services.menus import parse_timestamp

PAGE_SIZE = 1000
IN_CHUNK = 100


@dataclass(frozen=True)
class PublishedDish:
    menu_id: str
    dish_id: str
    scanned_at: datetime
    name: str
    name_key: str
    translations: dict
    price: float | int | None
    currency: str
    ai_result: dict


@dataclass(frozen=True)
class PublishedAnswer:
    menu_id: str
    name_key: str
    item_id: int
    answer: str  # APIの値
    confirmed_at: datetime


def _price(value) -> float | int | None:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _pages(build):
    offset = 0
    while True:
        rows = build().range(offset, offset + PAGE_SIZE - 1).execute().data
        yield from rows
        if len(rows) < PAGE_SIZE:
            return
        offset += PAGE_SIZE


def list_published_dishes(client: Client, google_place_id: str) -> list[PublishedDish]:
    rows = _pages(
        lambda: client.table("published_menus")
        .select("menu_id,dish_id,scanned_at,dish_name,name_key,translations,price,currency,ai_result")
        .eq("google_place_id", google_place_id)
        .order("menu_id")
        .order("dish_id")
    )
    return [
        PublishedDish(
            menu_id=row["menu_id"],
            dish_id=row["dish_id"],
            scanned_at=parse_timestamp(row["scanned_at"]),
            name=row["dish_name"],
            name_key=row["name_key"],
            translations=row["translations"],
            price=_price(row["price"]),
            currency=row["currency"],
            ai_result=row["ai_result"],
        )
        for row in rows
    ]


def _published_answers(client, view, id_column, google_place_id, name_keys, item_ids, convert) -> list[PublishedAnswer]:
    if not name_keys or not item_ids:
        return []
    keys = sorted(set(name_keys))
    result = []
    for start in range(0, len(keys), IN_CHUNK):
        chunk = keys[start : start + IN_CHUNK]
        rows = _pages(
            lambda: client.table(view)
            .select(f"session_id,menu_id,name_key,{id_column},answer,confirmed_at")
            .eq("google_place_id", google_place_id)
            .in_("name_key", chunk)
            .in_(id_column, sorted(set(item_ids)))
            .order("session_id")
            .order("dish_id")
            .order(id_column)
        )
        result.extend(
            PublishedAnswer(
                menu_id=row["menu_id"],
                name_key=row["name_key"],
                item_id=row[id_column],
                answer=convert(row["answer"]),
                confirmed_at=parse_timestamp(row["confirmed_at"]),
            )
            for row in rows
        )
    return result


def list_published_allergen_answers(client, google_place_id, name_keys, allergen_ids) -> list[PublishedAnswer]:
    return _published_answers(
        client, "published_confirmation_answers", "allergen_id", google_place_id, name_keys, allergen_ids,
        allergen_answer_from_db,
    )


def list_published_dietary_answers(client, google_place_id, name_keys, dietary_ids) -> list[PublishedAnswer]:
    return _published_answers(
        client, "published_dietary_answers", "dietary_restriction_id", google_place_id, name_keys, dietary_ids,
        dietary_answer_from_db,
    )


def representative_dishes(dishes: list[PublishedDish]) -> list[PublishedDish]:
    """`name_key` ごとの代表料理（撮影日時が最新、同日時は料理IDの降順）を、撮影日時の降順・name_key順で返す。"""
    chosen: dict[str, PublishedDish] = {}
    for dish in dishes:
        kept = chosen.get(dish.name_key)
        if kept is None or (dish.scanned_at, dish.dish_id) > (kept.scanned_at, kept.dish_id):
            chosen[dish.name_key] = dish
    by_key = sorted(chosen.values(), key=lambda d: d.name_key)
    return sorted(by_key, key=lambda d: d.scanned_at, reverse=True)


def _allergen_targets(dish: PublishedDish, allergen_ids: list[int] | None, masters: dict[int, MasterName]) -> list[int]:
    return allergen_target_ids(dish.ai_result, allergen_ids, masters)


def _history(answers: list[PublishedAnswer], name_key: str, item_id: int) -> list[HistoryAnswer]:
    return [
        HistoryAnswer(a.menu_id, a.answer, a.confirmed_at)
        for a in answers
        if a.name_key == name_key and a.item_id == item_id
    ]


def build_public_menus(
    client: Client,
    *,
    google_place_id: str,
    allergen_ids: list[int] | None,
    dietary_restriction_ids: list[int],
    allergen_masters: dict[int, MasterName],
    dietary_masters: dict[int, MasterName],
    now: datetime,
    half_life_days: float,
) -> PublicMenusResponse:
    dishes = representative_dishes(list_published_dishes(client, google_place_id))
    name_keys = [dish.name_key for dish in dishes]
    target_allergens = sorted({i for dish in dishes for i in _allergen_targets(dish, allergen_ids, allergen_masters)})
    dietary_ids = sorted(set(dietary_restriction_ids))
    allergen_answers = list_published_allergen_answers(client, google_place_id, name_keys, target_allergens)
    dietary_answers = list_published_dietary_answers(client, google_place_id, name_keys, dietary_ids)

    results = []
    for dish in dishes:
        allergen_ai = ai_candidates(dish.ai_result, "allergens", "allergen_id")
        dietary_ai = ai_candidates(dish.ai_result, "dietary_restrictions", "dietary_restriction_id")
        allergens = []
        for allergen_id in _allergen_targets(dish, allergen_ids, allergen_masters):
            result = assess_item(
                allergen_ai.get(allergen_id, UNKNOWN_AI), None, _history(allergen_answers, dish.name_key, allergen_id),
                ALLERGEN_SCALE, now, half_life_days,
            )
            parts = allergen_parts(result)
            allergens.append(
                PublicAllergenAssessment(
                    allergen_id=allergen_id,
                    display_name=allergen_masters[allergen_id].display_name,
                    ai=parts["ai"],
                    store_history=parts["store_history"],
                    notices=PublicAllergenNotices(
                        history_conflict=result.notices.history_conflict,
                        history_shared_utensils=result.notices.history_separate,
                    ),
                )
            )
        dietary = []
        for dietary_id in dietary_ids:
            result = assess_item(
                dietary_ai.get(dietary_id, UNKNOWN_AI), None, _history(dietary_answers, dish.name_key, dietary_id),
                DIETARY_SCALE, now, half_life_days,
            )
            parts = dietary_parts(result)
            dietary.append(
                PublicDietaryAssessment(
                    dietary_restriction_id=dietary_id,
                    display_name=dietary_masters[dietary_id].display_name,
                    ai=parts["ai"],
                    store_history=parts["store_history"],
                    notices=PublicDietaryNotices(
                        history_conflict=result.notices.history_conflict,
                        history_cross_contact=result.notices.history_separate,
                    ),
                )
            )
        english = (dish.translations or {}).get("en") or {}
        results.append(
            PublicDish(
                name_key=dish.name_key,
                name=dish.name,
                display_name=english.get("name", ""),
                description=english.get("description", ""),
                price=dish.price,
                currency=dish.currency,
                allergens=allergens,
                dietary_restrictions=dietary,
            )
        )
    return PublicMenusResponse(
        google_place_id=google_place_id, match_basis="name_key", staff_answers_verified=False, dishes=results
    )
