"""アカウント用トークン（HS256署名のJWT）と、登録・ログイン（P1、06）。

- トークンの中身は `sub`（accounts.id）・`iat`・`exp`・`typ="account"` だけ。DBに保存しない。
- 検証項目：署名（HS256のみ）・期限・`typ`・`sub`（UUID）・アカウントの存在。どれかが不正なら401で、
  無効な認証をゲストとして扱わない。解析用トークンはJWTではないため、ここでは常に401になる。
- パスワードはArgon2id（argon2-cffiの既定パラメータ）のハッシュだけを保存する。平文・ハッシュ・トークン・
  メールアドレスはログに残さない。
- ログインはアカウントがなくてもダミーのハッシュで照合し、失敗はすべて401 `invalid_credentials`。
"""

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from email_validator import EmailNotValidError, validate_email
from postgrest.exceptions import APIError
from supabase import Client

from app.config import Settings
from app.errors import ApiError

ALGORITHM = "HS256"
TOKEN_TYPE = "account"
MIN_SECRET_BYTES = 32
PUBLISH_CONSENT_VERSION = "2026-10-17-v1"
ACCOUNT_COLUMNS = "id,email,nickname,publish_consent,publish_consent_recorded_at,publish_consent_version,created_at"

_hasher = PasswordHasher()


@lru_cache
def _dummy_hash() -> str:
    """アカウントがない場合の照合用。応答時間の差を小さくする。"""
    return _hasher.hash(uuid.uuid4().hex)


# --- 入力の正規化・検証 ---


def _invalid() -> ApiError:
    return ApiError(422, "validation_error")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_registration(email: str, nickname: str, password: str) -> tuple[str, str]:
    """正規化したメール・ニックネームを返す。不正なら422。"""
    normalized = normalize_email(email)
    if not 3 <= len(normalized) <= 254:
        raise _invalid()
    try:
        validate_email(normalized, check_deliverability=False)
    except EmailNotValidError:
        raise _invalid() from None
    name = nickname.strip()
    if not 1 <= len(name) <= 30 or any(unicodedata.category(c) == "Cc" for c in name):
        raise _invalid()
    # 前後の空白は削らない。メールアドレスと同じ値は拒否する
    if not 8 <= len(password) <= 128 or password.strip().lower() == normalized:
        raise _invalid()
    return normalized, name


# --- トークン ---


def _secret(settings: Settings) -> str:
    return settings.auth_jwt_secret.get_secret_value() if settings.auth_jwt_secret else ""


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime


def issue_account_token(account_id: str, settings: Settings, now: datetime | None = None) -> IssuedToken:
    secret = _secret(settings)
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        # 署名鍵が未設定・短すぎる場合はトークンを発行しない（設定の誤り）
        raise ApiError(503, "service_unavailable")
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    expires_at = now + timedelta(hours=settings.account_token_ttl_hours)
    claims = {"sub": account_id, "iat": int(now.timestamp()), "exp": int(expires_at.timestamp()), "typ": TOKEN_TYPE}
    return IssuedToken(jwt.encode(claims, secret, algorithm=ALGORITHM), expires_at)


def verify_account_token(token: str, settings: Settings, db: Client) -> str:
    """有効なら `sub`（アカウントID）を返す。"""
    secret = _secret(settings)
    if not secret:
        # 署名鍵がなければ、このサーバーが発行した有効なトークンは存在しない
        raise ApiError(401, "unauthorized")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "iat", "exp", "typ"]},
        )
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "account_token_expired") from None
    except jwt.PyJWTError:
        raise ApiError(401, "unauthorized") from None

    if claims.get("typ") != TOKEN_TYPE:
        raise ApiError(401, "unauthorized")
    try:
        account_id = str(uuid.UUID(str(claims["sub"])))
    except ValueError:
        raise ApiError(401, "unauthorized") from None

    rows = db.table("accounts").select("id").eq("id", account_id).limit(1).execute().data
    if not rows:
        raise ApiError(401, "unauthorized")
    return account_id


# --- 登録・ログイン・本人情報 ---


def register_account(db: Client, *, email: str, nickname: str, password: str, publish_consent: bool) -> dict:
    """`accounts` に5列だけを追加する。重複メールは一意制約違反（23505）を409にする（事前のSELECTで判定しない）。"""
    try:
        rows = (
            db.table("accounts")
            .insert(
                {
                    "email": email,
                    "nickname": nickname,
                    "password_hash": _hasher.hash(password),
                    "publish_consent": publish_consent,
                    "publish_consent_version": PUBLISH_CONSENT_VERSION,
                }
            )
            .execute()
            .data
        )
    except APIError as exc:
        if exc.code == "23505":
            raise ApiError(409, "email_already_registered") from None
        raise
    return {key: rows[0][key] for key in ACCOUNT_COLUMNS.split(",")}


def authenticate(db: Client, *, email: str, password: str) -> str | None:
    """成功ならアカウントIDを返す。アカウントがなくてもダミーのハッシュで照合する。"""
    rows = db.table("accounts").select("id,password_hash").eq("email", normalize_email(email)).limit(1).execute().data
    row = rows[0] if rows else None
    stored = row["password_hash"] if row else _dummy_hash()
    try:
        _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return None
    if row is None:
        return None
    if _hasher.check_needs_rehash(stored):
        # 現行より弱いパラメータのハッシュは再ハッシュする（更新できるのはこの2列だけ）
        db.table("accounts").update(
            {"password_hash": _hasher.hash(password), "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", row["id"]).execute()
    return row["id"]


def get_account(db: Client, account_id: str) -> dict:
    rows = db.table("accounts").select(ACCOUNT_COLUMNS).eq("id", account_id).limit(1).execute().data
    if not rows:
        raise ApiError(401, "unauthorized")
    return rows[0]
