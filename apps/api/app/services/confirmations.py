"""店員確認（API 6）の入力検証・公開判定・結果の組み立て。

検証の順序と結果は `complete_confirmation_session` に合わせる（RPCも同じ検証をするため、APIで先に止める）：
合計1〜50回答・各要素の欠落／null／値 → 重複 → 未知の項目ID → 料理の和集合1〜10件 → メニューに属すること
（`dish_not_in_menu`）→ 各配列の直積 → 両配列が空でなければ料理集合の一致。
アレルゲンはAPIの値（`does_not_contain`・`shared_utensils` など）だけを受け付け、RPCへはDBの値で渡す。
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.errors import ApiError
from app.schemas.confirmations import (
    AllergenAnswerItem,
    AllergenConfirmationResult,
    ConfirmedDish,
    DietaryAnswerItem,
    DietaryConfirmationResult,
)
from app.services.answers import (
    ALLERGEN_ANSWERS,
    ALLERGEN_API_TO_DB,
    ALLERGEN_LABELS,
    DIETARY_ANSWERS,
    DIETARY_API_TO_DB,
    DIETARY_LABELS,
)
from app.services.assessment import (
    ALLERGEN_SCALE,
    DIETARY_SCALE,
    UNKNOWN_AI,
    HistoryAnswer,
    RecordedAnswer,
    assess_item,
)
from app.services.menu_results import MasterName, ai_candidates, allergen_parts, dietary_parts
from app.services.menus import DishRow, StoreAnswerRow

MAX_ANSWERS = 50
MAX_DISHES = 10


@dataclass(frozen=True)
class Answer:
    dish_id: str  # 小文字のUUID
    item_id: int
    answer: str  # APIの値


@dataclass(frozen=True)
class ValidatedAnswers:
    allergens: list[Answer]
    dietary: list[Answer]

    def rpc_answers(self) -> list[dict]:
        return [
            {"dish_id": a.dish_id, "allergen_id": a.item_id, "answer": ALLERGEN_API_TO_DB[a.answer]}
            for a in self.allergens
        ]

    def rpc_dietary_answers(self) -> list[dict]:
        return [
            {"dish_id": a.dish_id, "dietary_restriction_id": a.item_id, "answer": DIETARY_API_TO_DB[a.answer]}
            for a in self.dietary
        ]

    @property
    def dish_ids(self) -> set[str]:
        return {a.dish_id for a in self.allergens} | {a.dish_id for a in self.dietary}


def _invalid() -> ApiError:
    return ApiError(422, "answers_invalid")


def _normalize(
    items: Sequence[AllergenAnswerItem | DietaryAnswerItem], id_field: str, values: tuple[str, ...]
) -> list[Answer]:
    result = []
    for item in items:
        dish_id, item_id, answer = item.dish_id, getattr(item, id_field), item.answer
        # 欠落・nullは未回答。明示的な unknown は有効な回答
        if dish_id is None or item_id is None or answer is None or answer not in values:
            raise _invalid()
        try:
            dish = str(uuid.UUID(dish_id))
        except ValueError:
            raise _invalid() from None
        if len(dish_id) != 36:  # 波括弧・ハイフンなしなどの表記はRPCも拒否する
            raise _invalid()
        result.append(Answer(dish, item_id, answer))
    return result


def _is_full_product(answers: list[Answer]) -> bool:
    dishes = {a.dish_id for a in answers}
    items = {a.item_id for a in answers}
    return len(answers) == len(dishes) * len(items)


def validate_answers(
    answers: Sequence[AllergenAnswerItem],
    dietary_answers: Sequence[DietaryAnswerItem],
    *,
    allergen_ids: set[int],
    dietary_restriction_ids: set[int],
    menu_dish_ids: set[str],
) -> ValidatedAnswers:
    total = len(answers) + len(dietary_answers)
    if total < 1 or total > MAX_ANSWERS:
        raise _invalid()
    allergens = _normalize(answers, "allergen_id", ALLERGEN_ANSWERS)
    dietary = _normalize(dietary_answers, "dietary_restriction_id", DIETARY_ANSWERS)

    for group in (allergens, dietary):
        keys = [(a.dish_id, a.item_id) for a in group]
        if len(keys) != len(set(keys)):
            raise _invalid()
    if any(a.item_id not in allergen_ids for a in allergens) or any(
        a.item_id not in dietary_restriction_ids for a in dietary
    ):
        raise _invalid()

    validated = ValidatedAnswers(allergens, dietary)
    if not 1 <= len(validated.dish_ids) <= MAX_DISHES:
        raise _invalid()
    if not validated.dish_ids <= menu_dish_ids:
        raise ApiError(422, "dish_not_in_menu")
    if not _is_full_product(allergens) or not _is_full_product(dietary):
        raise _invalid()
    if allergens and dietary and {a.dish_id for a in allergens} != {a.dish_id for a in dietary}:
        raise _invalid()
    return validated


def is_public(*, restaurant_id: str | None, user_publish_consent: bool, publish_consent: bool) -> bool:
    """今回の確認の公開状態。別の確認の同意やゲストの同意は使わない。"""
    return restaurant_id is not None and user_publish_consent and publish_consent


def _history(
    rows: list[StoreAnswerRow] | None, name_key: str, item_id: int
) -> list[HistoryAnswer] | None:
    if rows is None:
        return None
    return [
        HistoryAnswer(r.menu_id, r.answer, r.confirmed_at) for r in rows if r.name_key == name_key and r.item_id == item_id
    ]


def build_results(
    *,
    dishes: list[DishRow],
    answers: ValidatedAnswers,
    confirmed_at: datetime,
    allergen_masters: dict[int, MasterName],
    dietary_masters: dict[int, MasterName],
    store_allergen_answers: list[StoreAnswerRow] | None,
    store_dietary_answers: list[StoreAnswerRow] | None,
    now: datetime,
    half_life_days: float,
) -> list[ConfirmedDish]:
    """回答した料理をメニューの順に、AIの候補と今回の店員回答（APIの値・英語ラベル）を分けて返す。"""
    allergen_by_dish: dict[str, list[Answer]] = {}
    dietary_by_dish: dict[str, list[Answer]] = {}
    for a in answers.allergens:
        allergen_by_dish.setdefault(a.dish_id, []).append(a)
    for a in answers.dietary:
        dietary_by_dish.setdefault(a.dish_id, []).append(a)

    results = []
    for dish in dishes:
        if dish.id not in answers.dish_ids:
            continue
        allergen_ai = ai_candidates(dish.ai_result, "allergens", "allergen_id")
        dietary_ai = ai_candidates(dish.ai_result, "dietary_restrictions", "dietary_restriction_id")
        allergens = []
        for a in sorted(allergen_by_dish.get(dish.id, []), key=lambda a: allergen_masters[a.item_id].display_order):
            result = assess_item(
                allergen_ai.get(a.item_id, UNKNOWN_AI),
                RecordedAnswer(a.answer, confirmed_at),
                _history(store_allergen_answers, dish.name_key, a.item_id),
                ALLERGEN_SCALE,
                now,
                half_life_days,
            )
            allergens.append(
                AllergenConfirmationResult(
                    allergen_id=a.item_id,
                    display_name=allergen_masters[a.item_id].display_name,
                    answer=a.answer,
                    answer_label=ALLERGEN_LABELS[a.answer],
                    **allergen_parts(result),
                )
            )
        dietary = []
        for a in sorted(dietary_by_dish.get(dish.id, []), key=lambda a: a.item_id):
            result = assess_item(
                dietary_ai.get(a.item_id, UNKNOWN_AI),
                RecordedAnswer(a.answer, confirmed_at),
                _history(store_dietary_answers, dish.name_key, a.item_id),
                DIETARY_SCALE,
                now,
                half_life_days,
            )
            dietary.append(
                DietaryConfirmationResult(
                    dietary_restriction_id=a.item_id,
                    display_name=dietary_masters[a.item_id].display_name,
                    answer=a.answer,
                    answer_label=DIETARY_LABELS[a.answer],
                    **dietary_parts(result),
                )
            )
        english = (dish.translations or {}).get("en") or {}
        results.append(
            ConfirmedDish(
                dish_id=dish.id,
                display_name=english.get("name", ""),
                allergens=allergens,
                dietary_restrictions=dietary,
            )
        )
    return results
