"""複数のVercelインスタンスで共有するレート制限。

保存先は Upstash Redis（REST API）。固定ウィンドウのカウンターを `/multi-exec`（トランザクション）で
`SET key 0 EX <window> NX` → `INCR key` の順に実行し、期限なしのキーが残らないようにする。
キーには識別子（IP・メールアドレス）のSHA-256だけを使い、生の値を保存先に送らない。

`MemoryRateLimiter` はプロセス内だけで数えるため、ローカル開発・テスト専用（Vercel上では設定検証で拒否）。
保存先が使えない場合は制限を素通りさせず 503 にする。
"""

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx
from fastapi import Depends

from app.config import Settings, get_settings
from app.errors import ApiError


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int


class RateLimiter(Protocol):
    def hit(self, rule: RateLimitRule, identifier: str) -> int:
        """カウンターを1増やし、現在のウィンドウ内の回数を返す。"""

    def count(self, rule: RateLimitRule, identifier: str) -> int:
        """増やさずに現在のウィンドウ内の回数を返す（ログイン失敗の判定用）。"""


def _window_key(rule: RateLimitRule, identifier: str, now: float) -> str:
    window = int(now // rule.window_seconds)
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return f"rl:{rule.name}:{rule.window_seconds}:{window}:{digest}"


class UpstashRateLimiter:
    def __init__(
        self,
        rest_url: str,
        rest_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=rest_url.rstrip("/"),
            headers={"Authorization": f"Bearer {rest_token}"},
            timeout=timeout_seconds,
            transport=transport,
        )
        self._clock = clock

    def hit(self, rule: RateLimitRule, identifier: str) -> int:
        key = _window_key(rule, identifier, self._clock())
        commands = [["SET", key, "0", "EX", str(rule.window_seconds), "NX"], ["INCR", key]]
        try:
            response = self._client.post("/multi-exec", json=commands)
            response.raise_for_status()
            body = response.json()
            count = body[1]["result"]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ApiError(503, "service_unavailable") from exc
        if not isinstance(count, int):
            raise ApiError(503, "service_unavailable")
        return count

    def count(self, rule: RateLimitRule, identifier: str) -> int:
        key = _window_key(rule, identifier, self._clock())
        try:
            response = self._client.post("/", json=["GET", key])
            response.raise_for_status()
            value = response.json()["result"]
            return 0 if value is None else int(value)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ApiError(503, "service_unavailable") from exc


class MemoryRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def hit(self, rule: RateLimitRule, identifier: str) -> int:
        key = _window_key(rule, identifier, self._clock())
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

    def count(self, rule: RateLimitRule, identifier: str) -> int:
        key = _window_key(rule, identifier, self._clock())
        with self._lock:
            return self._counts.get(key, 0)


_limiters: dict[tuple, RateLimiter] = {}
_limiters_lock = threading.Lock()


def get_rate_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    if settings.rate_limit_backend == "upstash":
        assert settings.upstash_redis_rest_url and settings.upstash_redis_rest_token
        cache_key = ("upstash", settings.upstash_redis_rest_url)
        factory: Callable[[], RateLimiter] = lambda: UpstashRateLimiter(  # noqa: E731
            settings.upstash_redis_rest_url, settings.upstash_redis_rest_token.get_secret_value()
        )
    else:
        cache_key = ("memory",)
        factory = MemoryRateLimiter
    with _limiters_lock:
        if cache_key not in _limiters:
            _limiters[cache_key] = factory()
        return _limiters[cache_key]


def enforce_rate_limit(limiter: RateLimiter, rule: RateLimitRule, identifier: str) -> None:
    """上限を超えたら 429 rate_limited。"""
    if limiter.hit(rule, identifier) > rule.limit:
        raise ApiError(429, "rate_limited")
