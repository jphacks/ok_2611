"""入出力モデルの共通部品。未定義フィールドはすべて拒否する。"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, PlainSerializer

Locale = Literal["en"]


def to_utc_iso(value: datetime) -> str:
    """UTCのISO 8601（末尾 `Z`）。タイムゾーンのない値はUTCとみなす。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[datetime, PlainSerializer(to_utc_iso, return_type=str, when_used="json")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoQuery(StrictModel):
    """クエリを受け付けないGET用。余分なクエリは422。"""


class LocaleQuery(StrictModel):
    locale: Locale = "en"


class ErrorBody(StrictModel):
    code: str
    message: str


class ErrorResponse(StrictModel):
    error: ErrorBody


# OpenAPIの422をFastAPI既定の形式ではなく共通エラー形式で出す
VALIDATION_ERROR_RESPONSES: dict[int | str, dict] = {
    422: {"model": ErrorResponse, "description": "未定義フィールド・不正な値（validation_error）"},
}
