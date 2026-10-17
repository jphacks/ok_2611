"""解析用トークン。

256bitの乱数をURL-safeにしたもの。DBにはSHA-256の小文字16進文字列だけを保存し、生のトークンは
解析成功時のレスポンスでだけ返す。比較は `hmac.compare_digest` で行う。アカウント用トークン（JWT）とは
形式も保存先も別で、互いに代用できない。
"""

import hashlib
import hmac
import secrets

from fastapi import Request

from app.errors import ApiError

ANALYSIS_TOKEN_BYTES = 32  # 256bit
ANALYSIS_TOKEN_TTL_HOURS = 24


def new_analysis_token() -> str:
    return secrets.token_urlsafe(ANALYSIS_TOKEN_BYTES)


def hash_analysis_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def analysis_token_matches(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_analysis_token(token).encode("ascii"), stored_hash.encode("ascii"))


def bearer_token(request: Request) -> str | None:
    """`Authorization: Bearer <token>` の値。ヘッダーがなければ None、形式が不正なら401。"""
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or " " in token:
        raise ApiError(401, "unauthorized")
    return token
