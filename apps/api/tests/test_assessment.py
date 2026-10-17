"""判定の計算（app/services/assessment.py）。algorithms.md と08の決定事項の例を確認する。"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.assessment import (
    ALLERGEN_SCALE,
    DIETARY_SCALE,
    UNKNOWN_AI,
    AiCandidate,
    HistoryAnswer,
    RecordedAnswer,
    ai_weight,
    assess_item,
    dedupe_latest_per_menu,
    evidence_weight,
    latest_answer,
    summarize_store_history,
    time_weight,
)

NOW = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
HALF_LIFE = 30.0
EXPLICIT = AiCandidate("explicit_present", "menu_text", "海老天")
POSSIBLE = AiCandidate("possible", "dish_name_inference", "Tempura usually uses shrimp.")


def answers(*values: str, days_ago: float = 0) -> list[HistoryAnswer]:
    # メニューごとに最新1件だけを数えるため、別々のメニューの回答として作る
    at = NOW - timedelta(days=days_ago)
    return [HistoryAnswer(menu_id=f"m{i}-{days_ago}", answer=v, confirmed_at=at) for i, v in enumerate(values)]


@pytest.mark.parametrize(("days", "weight"), [(0, 1.0), (30, 0.5), (60, 0.25)])
def test_time_weight_half_life(days, weight):
    assert time_weight(NOW - timedelta(days=days), NOW, HALF_LIFE) == pytest.approx(weight)


def test_time_weight_future_answer_is_not_boosted():
    assert time_weight(NOW + timedelta(days=3), NOW, HALF_LIFE) == 1.0


def test_algorithms_md_example():
    # 含まれる1・含まれない3・器具共有2・わからない1 → α=2、β=4、S≈0.333
    history = summarize_store_history(
        answers("contains", "does_not_contain", "does_not_contain", "does_not_contain",
                "shared_utensils", "shared_utensils", "unknown"),
        ALLERGEN_SCALE, NOW, HALF_LIFE,
    )
    assert history.alpha == 2.0
    assert history.beta == 4.0
    assert history.score == pytest.approx(0.333)
    assert history.answer_counts == {"contains": 1, "shared_utensils": 2, "does_not_contain": 3, "unknown": 1}
    assert history.has_conflict is True
    assert history.match_basis == "name_key"


def test_no_answers_is_none_and_unknown_only_has_null_score():
    assert summarize_store_history([], ALLERGEN_SCALE, NOW, HALF_LIFE) is None
    history = summarize_store_history(answers("unknown", "unknown"), ALLERGEN_SCALE, NOW, HALF_LIFE)
    assert history.score is None
    assert history.answer_counts["unknown"] == 2  # 不明は件数に入る
    assert (history.alpha, history.beta) == (1.0, 1.0)
    assert history.last_answered_at["unknown"] == NOW
    assert history.has_conflict is False


def test_shared_utensils_and_unknown_are_not_added_to_alpha_beta():
    history = summarize_store_history(answers("shared_utensils", "unknown"), ALLERGEN_SCALE, NOW, HALF_LIFE)
    assert (history.alpha, history.beta, history.score) == (1.0, 1.0, None)
    assert history.answer_counts["shared_utensils"] == 1
    assert history.last_answered_at == {"contains": None, "shared_utensils": NOW, "does_not_contain": None, "unknown": NOW}


def test_weighted_by_age():
    history = summarize_store_history(
        answers("contains", days_ago=30) + answers("does_not_contain", days_ago=0), ALLERGEN_SCALE, NOW, HALF_LIFE
    )
    assert history.alpha == 1.5
    assert history.beta == 2.0
    assert history.score == pytest.approx(1.5 / 3.5, abs=1e-3)
    assert history.last_confirmed_at == NOW


def test_dietary_uses_same_rule():
    history = summarize_store_history(
        answers("not_supported", "supported", "supported", "supported", "cross_contact", "cross_contact", "unknown"),
        DIETARY_SCALE, NOW, HALF_LIFE,
    )
    assert (history.alpha, history.beta) == (2.0, 4.0)
    assert history.score == pytest.approx(0.333)
    assert history.answer_counts == {"not_supported": 1, "cross_contact": 2, "supported": 3, "unknown": 1}
    only_separate = summarize_store_history(answers("cross_contact", "unknown"), DIETARY_SCALE, NOW, HALF_LIFE)
    assert only_separate.score is None


def test_allergen_and_dietary_values_are_not_mixed():
    with pytest.raises(ValueError):
        summarize_store_history(answers("not_supported"), ALLERGEN_SCALE, NOW, HALF_LIFE)
    with pytest.raises(ValueError):
        summarize_store_history(answers("contains"), DIETARY_SCALE, NOW, HALF_LIFE)


def test_dedupe_keeps_latest_answer_per_menu():
    rows = [
        HistoryAnswer("m1", "does_not_contain", NOW - timedelta(days=2)),
        HistoryAnswer("m1", "contains", NOW - timedelta(days=1)),
        HistoryAnswer("m2", "does_not_contain", NOW),
        # 同じ確認で同名の料理が2つある場合は案内順で先の回答
        HistoryAnswer("m3", "does_not_contain", NOW),
        HistoryAnswer("m3", "shared_utensils", NOW),
    ]
    kept = dedupe_latest_per_menu(rows, ALLERGEN_SCALE)
    assert {(a.menu_id, a.answer) for a in kept} == {("m1", "contains"), ("m2", "does_not_contain"), ("m3", "shared_utensils")}


def test_ai_weight_is_null_without_validation_data():
    assert ai_weight("menu_text") is None
    assert ai_weight("recipe_inference") is None
    assert ai_weight("unavailable") is None
    assert evidence_weight(0, 0) is None  # n=0 で0.5を出さない
    assert evidence_weight(98, 100) == pytest.approx(0.971)
    assert evidence_weight(58, 100) == pytest.approx(0.578)


def test_assess_item_keeps_ai_and_staff_separate():
    current = RecordedAnswer("does_not_contain", NOW)
    result = assess_item(EXPLICIT, current, answers("contains"), ALLERGEN_SCALE, NOW, HALF_LIFE)
    # AIは記載のまま、店員回答もそのまま。合成した値はない
    assert result.ai == EXPLICIT
    assert result.ai_weight is None
    assert result.current_answer == current
    assert result.store_history.answer_counts["contains"] == 1
    assert result.notices.ai_staff_mismatch is True
    assert not hasattr(result, "prediction")


@pytest.mark.parametrize(
    ("ai", "current", "mismatch", "recheck"),
    [
        (EXPLICIT, "does_not_contain", True, False),
        # AIの含有候補と器具共有は両立するため不一致にしない
        (EXPLICIT, "shared_utensils", False, False),
        (EXPLICIT, "contains", False, False),
        (EXPLICIT, "unknown", False, True),
        # 推定の候補（記載ではない）と「含まれない」は食い違いとして扱わない
        (POSSIBLE, "does_not_contain", False, False),
        (UNKNOWN_AI, "does_not_contain", False, False),
        (EXPLICIT, None, False, False),
    ],
)
def test_notices_for_current_answer(ai, current, mismatch, recheck):
    recorded = RecordedAnswer(current, NOW) if current else None
    result = assess_item(ai, recorded, [], ALLERGEN_SCALE, NOW, HALF_LIFE)
    assert result.notices.ai_staff_mismatch is mismatch
    assert result.notices.recheck_current_answer is recheck
    assert result.store_history is None  # 範囲内の回答0件


def test_history_notices_and_no_store():
    result = assess_item(POSSIBLE, None, answers("contains", "does_not_contain", "shared_utensils"), ALLERGEN_SCALE, NOW, HALF_LIFE)
    assert result.notices.history_conflict is True
    assert result.notices.history_separate is True
    assert result.current_answer is None  # 未回答は null（unknown と区別）
    no_store = assess_item(POSSIBLE, None, None, ALLERGEN_SCALE, NOW, HALF_LIFE)
    assert no_store.store_history is None
    assert no_store.notices.history_conflict is False


def test_dietary_mismatch_uses_supported():
    explicit = AiCandidate("explicit_conflict", "menu_text", "豚")
    result = assess_item(explicit, RecordedAnswer("supported", NOW), [], DIETARY_SCALE, NOW, HALF_LIFE)
    assert result.notices.ai_staff_mismatch is True
    result = assess_item(explicit, RecordedAnswer("cross_contact", NOW), [], DIETARY_SCALE, NOW, HALF_LIFE)
    assert result.notices.ai_staff_mismatch is False


def test_latest_answer():
    older = RecordedAnswer("contains", NOW - timedelta(hours=1))
    newer = RecordedAnswer("unknown", NOW)
    assert latest_answer([older, newer]) == newer
    assert latest_answer([]) is None
