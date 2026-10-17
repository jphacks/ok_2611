"""アカウント用トークン（HS256署名のJWT）の検証。発行は06で追加する。

検証項目：署名（HS256のみ）・期限・`typ="account"`・`sub`（UUID）・アカウントの存在。どれかが不正なら401で、
無効な認証をゲストとして扱わない。解析用トークンはJWTではないため、ここでは常に401になる。
トークン・`sub` はログに残さない。
"""

import uuid

import jwt
from supabase import Client

from app.config import Settings
from app.errors import ApiError

ALGORITHM = "HS256"
TOKEN_TYPE = "account"


def verify_account_token(token: str, settings: Settings, db: Client) -> str:
    """有効なら `sub`（アカウントID）を返す。"""
    secret = settings.auth_jwt_secret.get_secret_value() if settings.auth_jwt_secret else ""
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
