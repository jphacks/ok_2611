"""共通エラー形式 `{"error": {"code", "message"}}` と例外ハンドラー。

入力値・SQLの本文・外部APIの応答・トークンはエラー本文にもログにも含めない。
エラー応答は常に `Cache-Control: no-store`。
"""

import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from postgrest.exceptions import APIError as PostgrestAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.db_errors import translate_db_error

logger = logging.getLogger("app.errors")

NO_STORE = "no-store"

DEFAULT_MESSAGES: dict[str, str] = {
    "unauthorized": "Authentication is required.",
    "invalid_analysis_token": "The analysis token is invalid.",
    "account_token_expired": "The account token has expired. Please log in again.",
    "not_found": "The resource was not found.",
    "place_not_found": "The place was not found.",
    "image_too_large": "The image exceeds the 2 MiB limit.",
    "unsupported_image_type": "Choose a JPEG or PNG image.",
    "unreadable_menu": "No dishes could be read from the image. Please take a new photo.",
    "invalid_ai_output": "The analysis service returned an invalid result.",
    "method_not_allowed": "The method is not allowed for this resource.",
    "request_id_conflict": "The request_id was already used with different content.",
    "email_already_registered": "This email address is already registered.",
    "conflict": "The request conflicts with existing data.",
    "analysis_expired": "The analysis has expired. Please take a new photo.",
    "validation_error": "The request is invalid.",
    "answers_invalid": "The answers are incomplete or invalid.",
    "dish_not_in_menu": "A dish does not belong to this menu.",
    "confirmation_limit_reached": "This menu has reached the confirmation limit.",
    "invalid_allergen_ids": "The allergen IDs are invalid.",
    "invalid_dietary_restriction_ids": "The dietary restriction IDs are invalid.",
    "rate_limited": "Too many requests. Please try again later.",
    "service_unavailable": "The service is temporarily unavailable.",
    "timeout": "The request timed out.",
    "internal_error": "An unexpected error occurred.",
}


class ApiError(Exception):
    """APIとして返すエラー。message はクライアント向けの固定の英文だけを使う。"""

    def __init__(self, status_code: int, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message or DEFAULT_MESSAGES.get(code, DEFAULT_MESSAGES["internal_error"])


def error_response(status_code: int, code: str, message: str | None = None) -> JSONResponse:
    error = ApiError(status_code, code, message)
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
        headers={"Cache-Control": NO_STORE},
    )


def _route_label(request: Request) -> str:
    # クエリ（座標など）を含めない。ルートが分かればテンプレート、なければパスだけ。
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message)


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI既定の detail は入力値（input）を含むため返さない。ログにも残さない。
    return error_response(422, "validation_error")


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(404, "not_found")
    if exc.status_code == 405:
        response = error_response(405, "method_not_allowed")
        if exc.headers and "Allow" in exc.headers:
            response.headers["Allow"] = exc.headers["Allow"]
        return response
    if exc.status_code >= 500:
        return error_response(exc.status_code, "internal_error")
    return error_response(exc.status_code, "validation_error")


async def _db_error_handler(request: Request, exc: PostgrestAPIError) -> JSONResponse:
    error = translate_db_error(exc)
    # SQLSTATEだけを記録する。message・details・hint は入力値を含みうるため記録しない。
    logger.warning(
        "db_error sqlstate=%s status=%s route=%s", exc.code, error.status_code, _route_label(request)
    )
    return error_response(error.status_code, error.code)


async def _upstream_error_handler(request: Request, exc: httpx.HTTPError) -> JSONResponse:
    # 例外の文字列はURL（キー・座標を含みうる）を含むため記録しない。
    logger.warning("upstream_error type=%s route=%s", type(exc).__name__, _route_label(request))
    if isinstance(exc, httpx.TimeoutException):
        return error_response(504, "timeout")
    return error_response(503, "service_unavailable")


async def _response_validation_error_handler(
    request: Request, exc: ResponseValidationError
) -> JSONResponse:
    logger.error("response_validation_error route=%s", _route_label(request))
    return error_response(500, "internal_error")


async def unhandled_error_middleware(request: Request, call_next):
    """想定外の例外を共通形式の500にする（CORSの内側で処理し、CORSヘッダーを付ける）。"""
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001
        # 例外のメッセージ・トレースバックは機密値を含みうるため型名だけを記録する。
        logger.error("unhandled_error type=%s route=%s", type(exc).__name__, _route_label(request))
        return error_response(500, "internal_error")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(PostgrestAPIError, _db_error_handler)
    app.add_exception_handler(httpx.HTTPError, _upstream_error_handler)
    app.add_exception_handler(ResponseValidationError, _response_validation_error_handler)
