"""API 8〜12・14〜17（P1）の入出力。パスワード・ハッシュ・トークン以外の本人情報だけを返す。"""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr

from app.schemas.common import Locale, StrictModel, UtcDatetime
from app.schemas.confirmations import ConfirmedDish
from app.schemas.menus import DishResult, PromptVersion


class RegisterRequest(StrictModel):
    email: Annotated[StrictStr, Field(max_length=320)]
    nickname: Annotated[StrictStr, Field(max_length=200)]
    password: Annotated[StrictStr, Field(max_length=1024, description="8〜128文字。前後の空白は削らない。")]
    publish_consent: StrictBool = Field(description="今後の読み込み結果の公開可否。明示的なtrue／falseが必須。")


class LoginRequest(StrictModel):
    email: Annotated[StrictStr, Field(max_length=320)]
    password: Annotated[StrictStr, Field(max_length=1024)]


class Account(StrictModel):
    id: str
    email: str
    nickname: str
    publish_consent: bool
    publish_consent_recorded_at: UtcDatetime
    publish_consent_version: str
    created_at: UtcDatetime


class AuthResponse(StrictModel):
    account: Account
    access_token: str
    token_type: Literal["bearer"]
    expires_at: UtcDatetime


class AllergenIds(StrictModel):
    allergen_ids: Annotated[list[StrictInt], Field(max_length=29)]


class DietaryRestrictionIds(StrictModel):
    dietary_restriction_ids: Annotated[list[StrictInt], Field(max_length=4)]


class HistoryQuery(StrictModel):
    google_place_id: Annotated[str | None, Field(min_length=1, max_length=255)] = None
    limit: Annotated[int, Field(ge=1, le=50)] = 20
    cursor: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    locale: Locale = "en"


class HistoryMenu(StrictModel):
    menu_id: str
    google_place_id: str | None
    scanned_at: UtcDatetime
    dish_names: list[str]
    dish_count: int
    confirmation_count: int
    is_public: bool


class HistoryResponse(StrictModel):
    menus: list[HistoryMenu]
    next_cursor: str | None


class ConfirmationRecord(StrictModel):
    session_id: str
    confirmed_at: UtcDatetime
    publish_consent: bool
    is_public: bool
    results: Annotated[list[ConfirmedDish], Field(min_length=1, max_length=10)]


class MenuDetailResponse(StrictModel):
    menu_id: str
    google_place_id: str | None
    ai_model: str
    prompt_version: PromptVersion
    analyzed_at: UtcDatetime
    locale: Locale
    dishes: Annotated[list[DishResult], Field(min_length=1, max_length=20)]
    user_publish_consent: bool
    is_public: bool = Field(description="このメニューに公開される確認が1件以上あるか。")
    confirmations: list[ConfirmationRecord] = Field(description="このメニューの確認だけ（新しい順）。")
