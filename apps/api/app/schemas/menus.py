"""API 4 `POST /menus/analyze`・API 5 `GET /menus/{menu_id}` の入出力。

判定の形は08の決定事項に従う（`prediction`・`basis`・`vote_shares` は廃止）。AIの候補（`ai`）、
今回の店員回答（`current_answer`）、同じ店舗の過去の回答（`store_history`）を別々に返し、合成しない。
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.common import Locale, StrictModel, UtcDatetime
from app.services.answers import AllergenAnswer, DietaryAnswer
from app.services.ai_classification import (
    ALLERGEN_STATUS_BY_SOURCE,
    DIETARY_STATUS_BY_SOURCE,
    validate_ai_classification,
)

PromptVersion = Literal["v4", "v5"]
Source = Literal["menu_text", "recipe_inference", "dish_name_inference", "unavailable"]


class MenuQuery(StrictModel):
    """API 5 のクエリ。対象IDはカンマ区切り（ルーターで検証する）。"""

    allergen_ids: str | None = None
    dietary_restriction_ids: str | None = None
    locale: Locale = "en"


class AllergenAi(StrictModel):
    status: Literal["explicit_present", "possible", "unknown"]
    source: Source
    evidence: str
    weight: float | None = Field(description="根拠の分類ごとの重み (c+1)/(n+2)。検証データがないMVPでは常にnull。")

    @model_validator(mode="after")
    def _check_classification(self) -> "AllergenAi":
        validate_ai_classification(self.status, self.source, self.evidence, ALLERGEN_STATUS_BY_SOURCE)
        return self


class DietaryAi(StrictModel):
    status: Literal["explicit_conflict", "possible_conflict", "unknown"]
    source: Source
    evidence: str
    weight: float | None

    @model_validator(mode="after")
    def _check_classification(self) -> "DietaryAi":
        validate_ai_classification(self.status, self.source, self.evidence, DIETARY_STATUS_BY_SOURCE)
        return self


class AllergenCurrentAnswer(StrictModel):
    answer: AllergenAnswer
    confirmed_at: UtcDatetime


class DietaryCurrentAnswer(StrictModel):
    answer: DietaryAnswer
    confirmed_at: UtcDatetime


class AllergenAnswerCounts(StrictModel):
    contains: int
    shared_utensils: int
    does_not_contain: int
    unknown: int


class AllergenAnswerDates(StrictModel):
    contains: UtcDatetime | None
    shared_utensils: UtcDatetime | None
    does_not_contain: UtcDatetime | None
    unknown: UtcDatetime | None


class DietaryAnswerCounts(StrictModel):
    not_supported: int
    cross_contact: int
    supported: int
    unknown: int


class DietaryAnswerDates(StrictModel):
    not_supported: UtcDatetime | None
    cross_contact: UtcDatetime | None
    supported: UtcDatetime | None
    unknown: UtcDatetime | None


class StoreHistoryBase(StrictModel):
    match_basis: Literal["name_key"] = Field(
        description="同じ店舗・料理名キー・項目IDで照合した暫定の集計であることを示す。"
    )
    last_confirmed_at: UtcDatetime
    alpha: float
    beta: float
    score: float | None = Field(
        description="S=α/(α+β)。含有・非含有を明示した回答内の傾向で、含有確率ではない。該当する回答が0件ならnull。"
    )
    has_conflict: bool


class AllergenStoreHistory(StoreHistoryBase):
    answer_counts: AllergenAnswerCounts
    last_answered_at: AllergenAnswerDates


class DietaryStoreHistory(StoreHistoryBase):
    answer_counts: DietaryAnswerCounts
    last_answered_at: DietaryAnswerDates


class AllergenNotices(StrictModel):
    ai_staff_mismatch: bool = Field(description="AIの含有記載と今回の「含まれない」が食い違う。再確認を案内する。")
    recheck_current_answer: bool = Field(description="今回の回答が「わからない」。")
    history_conflict: bool = Field(description="過去の「含まれる」と「含まれない」が混在する。")
    history_shared_utensils: bool = Field(description="過去に器具共有の回答がある。")


class DietaryNotices(StrictModel):
    ai_staff_mismatch: bool = Field(description="AIの抵触の記載と今回の「対応している」が食い違う。")
    recheck_current_answer: bool
    history_conflict: bool = Field(description="過去の「対応できない」と「対応している」が混在する。")
    history_cross_contact: bool


class AllergenAssessment(StrictModel):
    allergen_id: Annotated[int, Field(ge=1, le=29)]
    display_name: str
    ai: AllergenAi
    current_answer: AllergenCurrentAnswer | None
    store_history: AllergenStoreHistory | None
    notices: AllergenNotices


class DietaryAssessment(StrictModel):
    dietary_restriction_id: Annotated[int, Field(ge=1, le=4)]
    display_name: str
    ai: DietaryAi
    current_answer: DietaryCurrentAnswer | None
    store_history: DietaryStoreHistory | None
    notices: DietaryNotices


class DishResult(StrictModel):
    dish_id: str
    dish_version: int
    name: Annotated[str, Field(min_length=1, max_length=200)]
    display_name: str
    description: str
    price: float | int | None
    currency: str
    allergens: Annotated[list[AllergenAssessment], Field(max_length=29)]
    dietary_restrictions: Annotated[list[DietaryAssessment], Field(max_length=4)]


class MenuResponse(StrictModel):
    menu_id: str
    google_place_id: str | None
    ai_model: str
    prompt_version: PromptVersion
    analyzed_at: UtcDatetime
    locale: Locale
    dishes: Annotated[list[DishResult], Field(min_length=1, max_length=20)]
    analysis_expires_at: UtcDatetime


class AnalyzeResponse(MenuResponse):
    analysis_token: str = Field(description="解析用トークン。この応答でだけ返す。")
