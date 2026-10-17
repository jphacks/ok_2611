"""店員回答の値の対応（08の決定）。DBの値とAPIの値の変換はこのモジュールだけで行う。

アレルゲンはDBの値（`not_contains`・`cross_contact`）をAPIでは `does_not_contain`・`shared_utensils` と呼ぶ。
食事制限はDBとAPIで同じ値を使う。対応表は apps/api/README.md「店員回答の値の対応」。
"""

from typing import Literal

AllergenAnswer = Literal["contains", "does_not_contain", "shared_utensils", "unknown"]
DietaryAnswer = Literal["not_supported", "supported", "cross_contact", "unknown"]

# 画面の選択順の案内（含まれる → 器具共有 → 含まれない → わからない）と同じ並び
ALLERGEN_ANSWERS: tuple[AllergenAnswer, ...] = ("contains", "shared_utensils", "does_not_contain", "unknown")
DIETARY_ANSWERS: tuple[DietaryAnswer, ...] = ("not_supported", "cross_contact", "supported", "unknown")

ALLERGEN_DB_TO_API: dict[str, AllergenAnswer] = {
    "contains": "contains",
    "not_contains": "does_not_contain",
    "cross_contact": "shared_utensils",
    "unknown": "unknown",
}
ALLERGEN_API_TO_DB: dict[str, str] = {api: db for db, api in ALLERGEN_DB_TO_API.items()}

DIETARY_DB_TO_API: dict[str, DietaryAnswer] = {value: value for value in DIETARY_ANSWERS}
DIETARY_API_TO_DB: dict[str, str] = {value: value for value in DIETARY_ANSWERS}


class UnknownAnswerValue(ValueError):
    """DBに想定外の値がある（マイグレーションのCHECK制約と不一致）。"""


def allergen_answer_from_db(value: str) -> AllergenAnswer:
    try:
        return ALLERGEN_DB_TO_API[value]
    except KeyError:
        raise UnknownAnswerValue("allergen answer") from None


def dietary_answer_from_db(value: str) -> DietaryAnswer:
    try:
        return DIETARY_DB_TO_API[value]
    except KeyError:
        raise UnknownAnswerValue("dietary answer") from None


# 結果画面（⑮）の英語ラベル。「含まれない」は交差接触が未確認、器具共有は含有が未確認と分かる文言にする。
# 「安全」「食べられる」「対応を保証」に当たる語は使わない
ALLERGEN_LABELS: dict[str, str] = {
    "contains": "Contains",
    "shared_utensils": "Shares cooking utensils (ingredients not confirmed)",
    "does_not_contain": "Not an ingredient (cross-contact not confirmed)",
    "unknown": "Unknown",
}
DIETARY_LABELS: dict[str, str] = {
    "not_supported": "Not supported",
    "cross_contact": "Cross-contact",
    "supported": "Supported (staff answer)",
    "unknown": "Unknown",
}
