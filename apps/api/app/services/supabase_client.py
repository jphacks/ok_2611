"""サーバー用のSupabaseクライアント。

`SUPABASE_SECRET_KEY`（RLSを迂回する）で操作するため、権限はAPIで検証する。
ルーターは `Depends(get_supabase_client)` で受け取り、テストでは `app.dependency_overrides` で差し替える。
"""

from functools import lru_cache

from fastapi import Depends
from supabase import Client, create_client

from app.config import Settings, get_settings
from app.errors import ApiError


@lru_cache(maxsize=4)
def _create(url: str, secret_key: str) -> Client:
    return create_client(url, secret_key)


def get_supabase_client(settings: Settings = Depends(get_settings)) -> Client:
    if not settings.supabase_url or settings.supabase_secret_key is None:
        raise ApiError(503, "service_unavailable")
    return _create(settings.supabase_url, settings.supabase_secret_key.get_secret_value())
