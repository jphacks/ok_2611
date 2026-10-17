"""API 4・5 の応答の組み立て（AI・履歴・注意表示の部分はAPI 6でも使う）。判定は呼び出すたびに計算し、保存しない。

- 対象のアレルゲン：`allergen_ids` を指定すればその項目（候補がなければAIは `unknown`）、省略すれば
  料理ごとにAIが明示した項目（不明へ復旧したものも含む）。並びはマスタの表示順。
- 対象の食事制限：`dietary_restriction_ids` で指定した項目だけ。省略時は空配列。
- 利用者の選択設定は対象の選択にだけ使い、保存・ログ出力しない。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from supabase import Client

from app.schemas.menus import (
    AllergenAi,
    AllergenAnswerCounts,
    AllergenAnswerDates,
    AllergenAssessment,
    AllergenCurrentAnswer,
    AllergenNotices,
    AllergenStoreHistory,
    DishResult,
    DietaryAi,
    DietaryAnswerCounts,
    DietaryAnswerDates,
    DietaryAssessment,
    DietaryCurrentAnswer,
    DietaryNotices,
    DietaryStoreHistory,
    MenuResponse,
)
from app.services.assessment import (
    ALLERGEN_SCALE,
    DIETARY_SCALE,
    UNKNOWN_AI,
    AiCandidate,
    HistoryAnswer,
    ItemAssessment,
    RecordedAnswer,
    assess_item,
    latest_answer,
)
from app.services import masters as master_service
from app.services.menu_analysis import MasterItem
from app.services.menus import DishRow, MenuAnswer, MenuRow, StoreAnswerRow


@dataclass(frozen=True)
class MasterName:
    id: int
    display_name: str
    display_order: int


@dataclass(frozen=True)
class Targets:
    allergen_ids: list[int] | None  # None は省略（AIの候補を対象にする）
    dietary_restriction_ids: list[int]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_masters(
    db: Client,
) -> tuple[list[MasterItem], list[MasterItem], dict[int, MasterName], dict[int, MasterName]]:
    """Gemini用のマスタ全件と、表示名・表示順。"""
    allergens = master_service.list_allergens(db, "en")
    dietary = master_service.list_dietary_restrictions(db, "en")
    allergen_items = [MasterItem(a.id, a.code, a.name, a.name_en) for a in allergens]
    dietary_items = [MasterItem(d.id, d.code, d.name, d.display_name) for d in dietary]
    allergen_names = {a.id: MasterName(a.id, a.display_name, a.display_order) for a in allergens}
    dietary_names = {d.id: MasterName(d.id, d.display_name, d.id) for d in dietary}
    return allergen_items, dietary_items, allergen_names, dietary_names


def ai_candidates(ai_result: dict, key: str, id_key: str) -> dict[int, AiCandidate]:
    return {
        int(item[id_key]): AiCandidate(status=item["status"], source=item["source"], evidence=item["evidence"])
        for item in ai_result.get(key) or []
    }


def allergen_targets(dish: DishRow, targets: Targets, masters: dict[int, MasterName]) -> list[int]:
    return allergen_target_ids(dish.ai_result, targets.allergen_ids, masters)


def allergen_target_ids(ai_result: dict, selected_ids: list[int] | None, masters: dict[int, MasterName]) -> list[int]:
    """公開・非公開で共通の対象選択。省略時も明示的な不明を消さない。"""
    if selected_ids is not None:
        ids = selected_ids
    else:
        ids = list(ai_candidates(ai_result, "allergens", "allergen_id"))
    return sorted(set(ids), key=lambda item_id: masters[item_id].display_order)


def history_item_ids(dishes: list[DishRow], targets: Targets, masters: dict[int, MasterName]) -> list[int]:
    ids: set[int] = set()
    for dish in dishes:
        ids.update(allergen_targets(dish, targets, masters))
    return sorted(ids)


def _group_menu_answers(answers: list[MenuAnswer]) -> dict[tuple[str, int], list[RecordedAnswer]]:
    grouped: dict[tuple[str, int], list[RecordedAnswer]] = defaultdict(list)
    for answer in answers:
        grouped[(answer.dish_id, answer.item_id)].append(RecordedAnswer(answer.answer, answer.confirmed_at))
    return grouped


def _group_store_answers(rows: list[StoreAnswerRow] | None) -> dict[tuple[str, int], list[HistoryAnswer]] | None:
    if rows is None:
        return None
    grouped: dict[tuple[str, int], list[HistoryAnswer]] = defaultdict(list)
    for row in rows:
        grouped[(row.name_key, row.item_id)].append(HistoryAnswer(row.menu_id, row.answer, row.confirmed_at))
    return grouped


def build_menu_response(
    *,
    menu: MenuRow,
    dishes: list[DishRow],
    targets: Targets,
    allergen_masters: dict[int, MasterName],
    dietary_masters: dict[int, MasterName],
    menu_allergen_answers: list[MenuAnswer],
    menu_dietary_answers: list[MenuAnswer],
    store_allergen_answers: list[StoreAnswerRow] | None,
    store_dietary_answers: list[StoreAnswerRow] | None,
    now: datetime,
    half_life_days: float,
) -> MenuResponse:
    """`store_*_answers` が None なら店舗未選択（履歴は null）。"""
    current_allergen = _group_menu_answers(menu_allergen_answers)
    current_dietary = _group_menu_answers(menu_dietary_answers)
    store_allergen = _group_store_answers(store_allergen_answers)
    store_dietary = _group_store_answers(store_dietary_answers)
    dietary_ids = sorted(set(targets.dietary_restriction_ids))

    response_dishes = []
    for dish in dishes:
        allergen_ai = ai_candidates(dish.ai_result, "allergens", "allergen_id")
        dietary_ai = ai_candidates(dish.ai_result, "dietary_restrictions", "dietary_restriction_id")
        allergens = []
        for allergen_id in allergen_targets(dish, targets, allergen_masters):
            result = assess_item(
                allergen_ai.get(allergen_id, UNKNOWN_AI),
                latest_answer(current_allergen.get((dish.id, allergen_id), [])),
                None if store_allergen is None else store_allergen.get((dish.name_key, allergen_id), []),
                ALLERGEN_SCALE,
                now,
                half_life_days,
            )
            allergens.append(_allergen(allergen_id, allergen_masters[allergen_id].display_name, result))
        dietary = []
        for dietary_id in dietary_ids:
            result = assess_item(
                dietary_ai.get(dietary_id, UNKNOWN_AI),
                latest_answer(current_dietary.get((dish.id, dietary_id), [])),
                None if store_dietary is None else store_dietary.get((dish.name_key, dietary_id), []),
                DIETARY_SCALE,
                now,
                half_life_days,
            )
            dietary.append(_dietary(dietary_id, dietary_masters[dietary_id].display_name, result))
        english = (dish.translations or {}).get("en") or {}
        response_dishes.append(
            DishResult(
                dish_id=dish.id,
                dish_version=dish.version,
                name=dish.name,
                display_name=english.get("name", ""),
                description=english.get("description", ""),
                price=dish.price,
                currency=dish.currency,
                allergens=allergens,
                dietary_restrictions=dietary,
            )
        )

    first = dishes[0]
    return MenuResponse(
        menu_id=menu.id,
        google_place_id=menu.google_place_id,
        ai_model=first.ai_model,
        prompt_version=first.prompt_version,
        analyzed_at=first.analyzed_at,
        locale="en",
        dishes=response_dishes,
        analysis_expires_at=menu.analysis_expires_at,
    )


def allergen_parts(result: ItemAssessment) -> dict:
    """AIの候補・履歴・注意表示（API 4・5・6で共通）。"""
    history = result.store_history
    return {
        "ai": AllergenAi(
            status=result.ai.status, source=result.ai.source, evidence=result.ai.evidence, weight=result.ai_weight
        ),
        "store_history": (
            AllergenStoreHistory(
                match_basis=history.match_basis,
                answer_counts=AllergenAnswerCounts(**history.answer_counts),
                last_answered_at=AllergenAnswerDates(**history.last_answered_at),
                last_confirmed_at=history.last_confirmed_at,
                alpha=history.alpha,
                beta=history.beta,
                score=history.score,
                has_conflict=history.has_conflict,
            )
            if history
            else None
        ),
        "notices": AllergenNotices(
            ai_staff_mismatch=result.notices.ai_staff_mismatch,
            recheck_current_answer=result.notices.recheck_current_answer,
            history_conflict=result.notices.history_conflict,
            history_shared_utensils=result.notices.history_separate,
        ),
    }


def dietary_parts(result: ItemAssessment) -> dict:
    history = result.store_history
    return {
        "ai": DietaryAi(
            status=result.ai.status, source=result.ai.source, evidence=result.ai.evidence, weight=result.ai_weight
        ),
        "store_history": (
            DietaryStoreHistory(
                match_basis=history.match_basis,
                answer_counts=DietaryAnswerCounts(**history.answer_counts),
                last_answered_at=DietaryAnswerDates(**history.last_answered_at),
                last_confirmed_at=history.last_confirmed_at,
                alpha=history.alpha,
                beta=history.beta,
                score=history.score,
                has_conflict=history.has_conflict,
            )
            if history
            else None
        ),
        "notices": DietaryNotices(
            ai_staff_mismatch=result.notices.ai_staff_mismatch,
            recheck_current_answer=result.notices.recheck_current_answer,
            history_conflict=result.notices.history_conflict,
            history_cross_contact=result.notices.history_separate,
        ),
    }


def _allergen(allergen_id: int, display_name: str, result: ItemAssessment) -> AllergenAssessment:
    current = result.current_answer
    return AllergenAssessment(
        allergen_id=allergen_id,
        display_name=display_name,
        current_answer=AllergenCurrentAnswer(answer=current.answer, confirmed_at=current.confirmed_at) if current else None,
        **allergen_parts(result),
    )


def _dietary(dietary_id: int, display_name: str, result: ItemAssessment) -> DietaryAssessment:
    current = result.current_answer
    return DietaryAssessment(
        dietary_restriction_id=dietary_id,
        display_name=display_name,
        current_answer=DietaryCurrentAnswer(answer=current.answer, confirmed_at=current.confirmed_at) if current else None,
        **dietary_parts(result),
    )
