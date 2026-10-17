"""API 6 `POST /menus/{menu_id}/confirmations` の入出力。

回答の要素は欠落・null（未回答）や未知の値・旧値を `answers_invalid` として返すため、要素の項目は
省略可能・文字列として受け、`app.services.confirmations.validate_answers` で検証する。
本文の未定義フィールド（`user_publish_consent` など）・`request_id`／`publish_consent` の欠落・null・型違いは
422 `validation_error`。
"""

import uuid
from typing import Annotated

from pydantic import Field, StrictBool, StrictInt, StrictStr

from app.schemas.common import Locale, StrictModel, UtcDatetime
from app.schemas.menus import (
    AllergenAi,
    AllergenNotices,
    AllergenStoreHistory,
    DietaryAi,
    DietaryNotices,
    DietaryStoreHistory,
)
from app.services.answers import ALLERGEN_ANSWERS, DIETARY_ANSWERS, AllergenAnswer, DietaryAnswer


class AllergenAnswerItem(StrictModel):
    dish_id: StrictStr | None = None
    allergen_id: StrictInt | None = None
    answer: Annotated[
        StrictStr | None,
        Field(
            json_schema_extra={"enum": list(ALLERGEN_ANSWERS)},
            description="contains／shared_utensils／does_not_contain／unknown。旧値（not_contains・cross_contact）・欠落・nullは422 answers_invalid。",
        ),
    ] = None


class DietaryAnswerItem(StrictModel):
    dish_id: StrictStr | None = None
    dietary_restriction_id: StrictInt | None = None
    answer: Annotated[
        StrictStr | None,
        Field(
            json_schema_extra={"enum": list(DIETARY_ANSWERS)},
            description="not_supported／cross_contact／supported／unknown。欠落・nullは422 answers_invalid。",
        ),
    ] = None


class ConfirmationRequest(StrictModel):
    request_id: uuid.UUID = Field(description="店員確認カードを開いたときに画面が作るUUID。再送の判定に使う。")
    answers: list[AllergenAnswerItem]
    dietary_answers: list[DietaryAnswerItem]
    publish_consent: StrictBool = Field(description="店員の明示選択。利用者同意は解析時に保存した値を使う。")
    locale: Locale = "en"


class AllergenConfirmationResult(StrictModel):
    allergen_id: Annotated[int, Field(ge=1, le=29)]
    display_name: str
    answer: AllergenAnswer
    answer_label: str
    ai: AllergenAi
    store_history: AllergenStoreHistory | None
    notices: AllergenNotices


class DietaryConfirmationResult(StrictModel):
    dietary_restriction_id: Annotated[int, Field(ge=1, le=4)]
    display_name: str
    answer: DietaryAnswer
    answer_label: str
    ai: DietaryAi
    store_history: DietaryStoreHistory | None
    notices: DietaryNotices


class ConfirmedDish(StrictModel):
    dish_id: str
    display_name: str
    allergens: Annotated[list[AllergenConfirmationResult], Field(max_length=29)]
    dietary_restrictions: Annotated[list[DietaryConfirmationResult], Field(max_length=4)]


class ConfirmationResponse(StrictModel):
    session_id: str
    confirmed_at: UtcDatetime
    publish_consent: bool
    user_publish_consent: bool
    is_public: bool = Field(description="店舗あり・保存済みの利用者同意true・今回の店員同意trueの場合だけtrue。")
    replayed: bool
    results: Annotated[list[ConfirmedDish], Field(min_length=1, max_length=10)]
