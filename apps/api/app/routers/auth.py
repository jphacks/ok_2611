"""API 8 `POST /auth/register`・API 9 `POST /auth/login`（P1）。

- 登録：IP単位5回／時。ログイン：失敗だけをIP単位10回／分・メールアドレス単位5回／15分で数え、
  超えていれば照合せずに429（上限内なら成功・失敗にかかわらず照合する）。
- 応答には本人情報・アカウント用トークン（24時間）を返し、パスワード・ハッシュは返さない。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool
from supabase import Client

from app.config import Settings, get_settings
from app.dependencies import client_ip, no_store
from app.errors import ApiError
from app.schemas.accounts import Account, AuthResponse, LoginRequest, RegisterRequest
from app.schemas.common import VALIDATION_ERROR_RESPONSES, ErrorResponse
from app.services import auth as auth_service
from app.services.rate_limit import RateLimiter, RateLimitRule, enforce_rate_limit, get_rate_limiter
from app.services.supabase_client import get_supabase_client

router = APIRouter(tags=["P1"], responses=VALIDATION_ERROR_RESPONSES)

REGISTER_RATE_LIMIT = RateLimitRule(name="auth_register_ip", limit=5, window_seconds=3600)
LOGIN_FAILURE_IP = RateLimitRule(name="auth_login_fail_ip", limit=10, window_seconds=60)
LOGIN_FAILURE_EMAIL = RateLimitRule(name="auth_login_fail_email", limit=5, window_seconds=900)


def _auth_response(account: dict, settings: Settings) -> AuthResponse:
    issued = auth_service.issue_account_token(account["id"], settings)
    return AuthResponse(
        account=Account(**account), access_token=issued.token, token_type="bearer", expires_at=issued.expires_at
    )


@router.post(
    "/auth/register",
    operation_id="register_account",
    status_code=201,
    response_model=AuthResponse,
    dependencies=[Depends(no_store)],
    responses={
        409: {"model": ErrorResponse, "description": "email_already_registered"},
        429: {"model": ErrorResponse, "description": "rate_limited"},
    },
)
def register(
    body: RegisterRequest,
    ip: Annotated[str, Depends(client_ip)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Client, Depends(get_supabase_client)],
) -> AuthResponse:
    enforce_rate_limit(limiter, REGISTER_RATE_LIMIT, ip)
    email, nickname = auth_service.validate_registration(body.email, body.nickname, body.password)
    # 署名鍵がなければ登録前に止める（登録だけ成功してトークンを返せない状態を作らない）
    auth_service.issue_account_token("00000000-0000-0000-0000-000000000000", settings)
    account = auth_service.register_account(
        db, email=email, nickname=nickname, password=body.password, publish_consent=body.publish_consent
    )
    return _auth_response(account, settings)


@router.post(
    "/auth/login",
    operation_id="login_account",
    response_model=AuthResponse,
    dependencies=[Depends(no_store)],
    responses={
        401: {"model": ErrorResponse, "description": "invalid_credentials"},
        429: {"model": ErrorResponse, "description": "rate_limited"},
    },
)
async def login(
    body: LoginRequest,
    ip: Annotated[str, Depends(client_ip)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Client, Depends(get_supabase_client)],
) -> AuthResponse:
    email = auth_service.normalize_email(body.email)
    return await run_in_threadpool(_login, email, body.password, ip, limiter, settings, db)


def _login(email: str, password: str, ip: str, limiter: RateLimiter, settings: Settings, db: Client) -> AuthResponse:
    if limiter.count(LOGIN_FAILURE_IP, ip) >= LOGIN_FAILURE_IP.limit or (
        limiter.count(LOGIN_FAILURE_EMAIL, email) >= LOGIN_FAILURE_EMAIL.limit
    ):
        raise ApiError(429, "rate_limited")
    account_id = auth_service.authenticate(db, email=email, password=password)
    if account_id is None:
        limiter.hit(LOGIN_FAILURE_IP, ip)
        limiter.hit(LOGIN_FAILURE_EMAIL, email)
        raise ApiError(401, "invalid_credentials")
    return _auth_response(auth_service.get_account(db, account_id), settings)
