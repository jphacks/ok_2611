"""Supabase（PostgREST）のエラーをAPIのステータス・コードへ変換する。

PostgRESTが付けるHTTPステータスは API仕様と一致しないため使わず、`APIError.code`（SQLSTATE）と
`APIError.message` だけで判定する。対応表は apps/api/README.md「DBエラーの変換」。
"""

from dataclasses import dataclass

from postgrest.exceptions import APIError


@dataclass(frozen=True)
class DbErrorMapping:
    status_code: int
    code: str


# 22023 のうち、DBの message をそのままAPIの code にするもの
_PASSTHROUGH_22023 = frozenset(
    {
        "answers_invalid",
        "dish_not_in_menu",
        "confirmation_limit_reached",
        "invalid_allergen_ids",
        "invalid_dietary_restriction_ids",
        "validation_error",
    }
)

# 入力の制約違反（not null・外部キー・check・型・長さ）
_CONSTRAINT_422 = frozenset({"23502", "23503", "23514", "22P02", "22001", "22003", "22007", "22008"})

_INTERNAL = DbErrorMapping(500, "internal_error")


def translate_db_error(exc: APIError) -> DbErrorMapping:
    sqlstate = exc.code or ""
    message = (exc.message or "").strip()

    if sqlstate == "28000" and message == "invalid_analysis_token":
        return DbErrorMapping(401, "invalid_analysis_token")
    if sqlstate == "P0002":
        if message == "menu_not_found":
            return DbErrorMapping(404, "not_found")
        if message == "account_not_found":
            # トークンの sub に当たるアカウントがない＝トークン検証の失敗と同じ扱い
            return DbErrorMapping(401, "unauthorized")
        return DbErrorMapping(404, "not_found")
    if sqlstate == "P0003" and message == "analysis_expired":
        return DbErrorMapping(410, "analysis_expired")
    if sqlstate == "40001" and message == "request_id_conflict":
        return DbErrorMapping(409, "request_id_conflict")
    if sqlstate == "22023":
        if message in _PASSTHROUGH_22023:
            return DbErrorMapping(422, message)
        # restaurant_mismatch・dishes_invalid など。API側の入力検証で先に防ぐべきもの
        return DbErrorMapping(422, "validation_error")
    if sqlstate == "23505":
        if _mentions(exc, "accounts_email_key"):
            return DbErrorMapping(409, "email_already_registered")
        return DbErrorMapping(409, "conflict")
    if sqlstate in _CONSTRAINT_422:
        return DbErrorMapping(422, "validation_error")
    # 42501（権限）・55000（snapshot_is_immutable）・その他はAPIの実装誤りか想定外
    return _INTERNAL


def _mentions(exc: APIError, needle: str) -> bool:
    return any(needle in (part or "") for part in (exc.message, exc.details))
