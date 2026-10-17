"""ルーターで共通に使う依存。"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Response
from supabase import Client

from app.config import Settings, get_settings
from app.errors import NO_STORE, ApiError
from app.services import menus as menu_store
from app.services.menu_results import utcnow
from app.services.supabase_client import get_supabase_client
from app.services.tokens import analysis_token_matches, bearer_token


def no_store(response: Response) -> None:
    """解析・確認・アカウント・公開集計の応答に付ける（`dependencies=[Depends(no_store)]`）。"""
    response.headers["Cache-Control"] = NO_STORE


def client_ip(request: Request, settings: Settings = Depends(get_settings)) -> str:
    """レート制限用のクライアントIP。ログ・DBには記録しない。

    Vercel上では、Vercelが上書きする `x-vercel-forwarded-for`（なければ `x-real-ip`）を使う。
    それ以外では利用者が自由に付けられるため転送ヘッダーを信用せず、接続元を使う。
    """
    if settings.vercel:
        for header in ("x-vercel-forwarded-for", "x-real-ip"):
            value = request.headers.get(header, "").split(",", 1)[0].strip()
            if value:
                return value
    return request.client.host if request.client else "unknown"


@dataclass(frozen=True)
class AuthorizedMenu:
    menu: menu_store.MenuRow
    token: str


def authorized_menu(
    menu_id: uuid.UUID,
    request: Request,
    db: Annotated[Client, Depends(get_supabase_client)],
) -> AuthorizedMenu:
    """解析用トークンでメニューへの権限と期限を確認する（API 5・6）。

    依存として解決するため、本文・クエリの検証より先に401・404・410を返す。アカウント用トークンや
    `menu_id` を知っていることだけでは通さない。比較はSHA-256を `hmac.compare_digest` で行う。
    """
    token = bearer_token(request)
    if token is None:
        raise ApiError(401, "unauthorized")
    menu = menu_store.get_menu(db, str(menu_id))
    if menu is None:
        raise ApiError(404, "not_found")
    if not analysis_token_matches(token, menu.analysis_token_hash):
        raise ApiError(401, "invalid_analysis_token")
    if utcnow() >= menu.analysis_expires_at:
        raise ApiError(410, "analysis_expired")
    return AuthorizedMenu(menu=menu, token=token)
