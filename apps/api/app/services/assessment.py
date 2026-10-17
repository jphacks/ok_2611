"""料理×確認項目ごとの判定（apps/api/docs/algorithms.md、08の決定事項）。

AIの候補・今回の店員回答・同じ店舗の過去の回答を別々に返し、一つの値に合成しない。
「安全」「食べられる」に当たる値は返さない。結果は保存せず、呼び出すたびに計算する。

- AI：根拠の分類ごとの重み `w=(c+1)/(n+2)`。検証データがないMVPでは `n=0` のため常に `null`。
- 履歴：「含まれる」（食事制限は `not_supported`）を α、「含まれない」（`supported`）を β に
  `w=2^(-d/半減期)` で加算し、`S=α/(α+β)`。器具共有（`shared_utensils`・`cross_contact`）と
  `unknown` は加算せず件数・日時だけを返す。α・β に加算する回答が0件なら `S=null`。
- 照合は同じ店舗・`name_key`・項目IDによる暫定のもの（`match_basis="name_key"`）。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.services.answers import ALLERGEN_ANSWERS, DIETARY_ANSWERS

MATCH_BASIS = "name_key"
SECONDS_PER_DAY = 86_400

# 根拠の分類ごとの検証件数 (c, n)。店舗のレシピ・原材料表示と照合した検証データがないため空（重みは null）
AI_SOURCE_CALIBRATION: dict[str, tuple[int, int]] = {}


@dataclass(frozen=True)
class AnswerScale:
    """アレルゲン／食事制限の4択の扱い。値はAPIの値。"""

    answers: tuple[str, ...]
    alpha: str  # αに加算（含まれる・対応できない）
    beta: str  # βに加算（含まれない・対応している）
    separate: str  # 加算せず別に表示（器具共有・交差接触）
    explicit_ai_status: str  # AIの「含有記載あり」に当たるstatus
    unknown_ai_status: str = "unknown"


ALLERGEN_SCALE = AnswerScale(
    answers=ALLERGEN_ANSWERS,
    alpha="contains",
    beta="does_not_contain",
    separate="shared_utensils",
    explicit_ai_status="explicit_present",
)
DIETARY_SCALE = AnswerScale(
    answers=DIETARY_ANSWERS,
    alpha="not_supported",
    beta="supported",
    separate="cross_contact",
    explicit_ai_status="explicit_conflict",
)


@dataclass(frozen=True)
class AiCandidate:
    status: str
    source: str
    evidence: str


UNKNOWN_AI = AiCandidate(status="unknown", source="unavailable", evidence="")


@dataclass(frozen=True)
class RecordedAnswer:
    """今回のメニューの店員回答（APIの値）。"""

    answer: str
    confirmed_at: datetime


@dataclass(frozen=True)
class HistoryAnswer:
    """同じ店舗・name_key・項目IDの回答（非公開を含む。APIの値）。"""

    menu_id: str
    answer: str
    confirmed_at: datetime


@dataclass(frozen=True)
class StoreHistory:
    answer_counts: dict[str, int]
    last_answered_at: dict[str, datetime | None]
    last_confirmed_at: datetime
    alpha: float
    beta: float
    score: float | None
    has_conflict: bool
    match_basis: str = MATCH_BASIS


@dataclass(frozen=True)
class Notices:
    """algorithms.md 4章の注意表示に使う判定。該当するものは併記する。"""

    ai_staff_mismatch: bool  # AIの含有記載と今回の「含まれない」（食事制限は「対応している」）の食い違い
    recheck_current_answer: bool  # 今回の回答が「わからない」
    history_conflict: bool  # 過去の「含まれる」と「含まれない」の混在
    history_separate: bool  # 過去に器具共有（交差接触）の回答あり


@dataclass(frozen=True)
class ItemAssessment:
    ai: AiCandidate
    ai_weight: float | None
    current_answer: RecordedAnswer | None
    store_history: StoreHistory | None
    notices: Notices


def evidence_weight(correct: int, total: int) -> float | None:
    """根拠の分類ごとの重み `(c+1)/(n+2)`。検証件数0なら null（0.5を表示しない）。"""
    if total <= 0:
        return None
    return round((correct + 1) / (total + 2), 3)


def ai_weight(source: str) -> float | None:
    if source == UNKNOWN_AI.source:
        return None
    correct, total = AI_SOURCE_CALIBRATION.get(source, (0, 0))
    return evidence_weight(correct, total)


def time_weight(confirmed_at: datetime, now: datetime, half_life_days: float) -> float:
    """`2^(-d/半減期)`。d は経過日数（小数）。時計のずれで未来になった回答は d=0 とする。"""
    elapsed_days = max((now - confirmed_at).total_seconds(), 0.0) / SECONDS_PER_DAY
    return 2.0 ** (-elapsed_days / half_life_days)


def dedupe_latest_per_menu(answers: Iterable[HistoryAnswer], scale: AnswerScale) -> list[HistoryAnswer]:
    """同じメニューへの複数回の確認は、最新の1件だけを数える（08の初期案）。

    同じ日時の回答が複数ある（同じ確認で同名の料理が2つある）場合は、4択の案内順で先の回答を残す。
    """
    order = {answer: index for index, answer in enumerate(scale.answers)}
    latest: dict[str, HistoryAnswer] = {}
    for answer in answers:
        kept = latest.get(answer.menu_id)
        if (
            kept is None
            or answer.confirmed_at > kept.confirmed_at
            or (answer.confirmed_at == kept.confirmed_at and order[answer.answer] < order[kept.answer])
        ):
            latest[answer.menu_id] = answer
    return sorted(latest.values(), key=lambda a: (a.confirmed_at, a.menu_id))


def summarize_store_history(
    answers: Iterable[HistoryAnswer], scale: AnswerScale, now: datetime, half_life_days: float
) -> StoreHistory | None:
    """履歴の集計。範囲内の回答が0件なら None。"""
    answers = list(answers)
    if not answers:
        return None
    counts = {answer: 0 for answer in scale.answers}
    last: dict[str, datetime | None] = {answer: None for answer in scale.answers}
    alpha = beta = 1.0
    for item in answers:
        if item.answer not in counts:
            raise ValueError("answer is not in the scale")
        counts[item.answer] += 1
        previous = last[item.answer]
        if previous is None or item.confirmed_at > previous:
            last[item.answer] = item.confirmed_at
        if item.answer == scale.alpha:
            alpha += time_weight(item.confirmed_at, now, half_life_days)
        elif item.answer == scale.beta:
            beta += time_weight(item.confirmed_at, now, half_life_days)
    has_explicit = counts[scale.alpha] + counts[scale.beta] > 0
    return StoreHistory(
        answer_counts=counts,
        last_answered_at=last,
        last_confirmed_at=max(item.confirmed_at for item in answers),
        alpha=round(alpha, 3),
        beta=round(beta, 3),
        score=round(alpha / (alpha + beta), 3) if has_explicit else None,
        has_conflict=counts[scale.alpha] > 0 and counts[scale.beta] > 0,
    )


def latest_answer(answers: Iterable[RecordedAnswer]) -> RecordedAnswer | None:
    return max(answers, key=lambda a: a.confirmed_at, default=None)


def assess_item(
    ai: AiCandidate,
    current_answer: RecordedAnswer | None,
    history_answers: Iterable[HistoryAnswer] | None,
    scale: AnswerScale,
    now: datetime,
    half_life_days: float,
) -> ItemAssessment:
    """`history_answers` が None なら店舗未選択（履歴を使わない）。"""
    history = (
        None
        if history_answers is None
        else summarize_store_history(dedupe_latest_per_menu(history_answers, scale), scale, now, half_life_days)
    )
    current = current_answer.answer if current_answer else None
    notices = Notices(
        # AIの含有候補と器具共有の回答は両立するため、食い違いに数えない
        ai_staff_mismatch=ai.status == scale.explicit_ai_status and current == scale.beta,
        recheck_current_answer=current == "unknown",
        history_conflict=history.has_conflict if history else False,
        history_separate=history.answer_counts[scale.separate] > 0 if history else False,
    )
    return ItemAssessment(
        ai=ai,
        ai_weight=ai_weight(ai.source),
        current_answer=current_answer,
        store_history=history,
        notices=notices,
    )
