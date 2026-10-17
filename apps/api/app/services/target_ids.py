"""判定の対象ID（`allergen_ids`・`dietary_restriction_ids`）の受け取り。API 4・5・7・17で共通。

- multipart（API 4）は同名partの繰り返し、クエリ（API 5・7・17）はカンマ区切り1つ。
- 形式の誤り（数字以外・空要素・同名クエリの繰り返し）は422 `validation_error`、
  未知・重複のIDは422 `invalid_allergen_ids`／`invalid_dietary_restriction_ids`。
- 対象IDは判定の対象選択にだけ使い、保存・ログ出力しない。
"""

import re

from fastapi import Request

from app.errors import ApiError

_ID_PATTERN = re.compile(r"^[0-9]{1,3}$")


def invalid() -> ApiError:
    return ApiError(422, "validation_error")


def parse_id_list(values: list) -> list[int] | None:
    """同名partの繰り返し。カンマ区切りやJSON配列の文字列は受け付けない。"""
    if not values:
        return None
    ids = []
    for value in values:
        if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
            raise invalid()
        ids.append(int(value))
    return ids


def parse_query_ids(request: Request, name: str, raw: str | None) -> list[int] | None:
    """カンマ区切り1つだけを受け付ける（同名クエリの繰り返しは422）。"""
    if len(request.query_params.getlist(name)) > 1:
        raise invalid()
    if raw is None:
        return None
    return parse_id_list(raw.split(","))


def check_ids(ids: list[int] | None, known: set[int], code: str) -> None:
    if ids is None:
        return
    if len(ids) != len(set(ids)) or not set(ids) <= known:
        raise ApiError(422, code)
