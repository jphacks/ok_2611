"""API 7 `GET /places/{google_place_id}/public-menus` の出力。

公開集計は個別の確認ではないため「今回の回答」（`current_answer`）はなく、注意表示は履歴の判定だけを返す。
所有者・menu／dish／sessionのID・個別の確認・画像・トークン・本人設定は含めない。
"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import Locale, StrictModel
from app.schemas.menus import (
    AllergenAi,
    AllergenStoreHistory,
    DietaryAi,
    DietaryStoreHistory,
)


class PublicMenusQuery(StrictModel):
    allergen_ids: str | None = None
    dietary_restriction_ids: str | None = None
    locale: Locale = "en"


class PublicAllergenNotices(StrictModel):
    history_conflict: bool = Field(description="公開回答に「含まれる」と「含まれない」が混在する。")
    history_shared_utensils: bool = Field(description="公開回答に器具共有がある。")


class PublicDietaryNotices(StrictModel):
    history_conflict: bool
    history_cross_contact: bool


class PublicAllergenAssessment(StrictModel):
    allergen_id: Annotated[int, Field(ge=1, le=29)]
    display_name: str
    ai: AllergenAi
    store_history: AllergenStoreHistory | None
    notices: PublicAllergenNotices


class PublicDietaryAssessment(StrictModel):
    dietary_restriction_id: Annotated[int, Field(ge=1, le=4)]
    display_name: str
    ai: DietaryAi
    store_history: DietaryStoreHistory | None
    notices: PublicDietaryNotices


class PublicDish(StrictModel):
    name_key: str
    name: str
    display_name: str
    description: str
    price: float | int | None
    currency: str
    allergens: Annotated[list[PublicAllergenAssessment], Field(max_length=29)]
    dietary_restrictions: Annotated[list[PublicDietaryAssessment], Field(max_length=4)]


class PublicMenusResponse(StrictModel):
    google_place_id: str
    match_basis: Literal["name_key"] = Field(description="同じ店舗の料理名キーで照合した暫定の集計。")
    staff_answers_verified: Literal[False] = Field(
        description="店員の回答は利用者の端末で入力された未認証のもの。店舗関係者かどうかは確認していない。"
    )
    dishes: list[PublicDish]
