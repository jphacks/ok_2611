import json

import httpx
import pytest

from app.errors import ApiError
from app.services.rate_limit import (
    MemoryRateLimiter,
    RateLimitRule,
    UpstashRateLimiter,
    enforce_rate_limit,
)

RULE = RateLimitRule(name="nearby_ip", limit=2, window_seconds=60)


class FakeUpstash:
    """Upstash REST の /multi-exec を真似る。複数インスタンスで共有される保存先の代わり。"""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttl: dict[str, int] = {}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == "/multi-exec"
        results = []
        for command in json.loads(request.content):
            if command[0] == "SET":
                _, key, value, _ex, seconds, _nx = command
                if key not in self.store:
                    self.store[key] = int(value)
                    self.ttl[key] = int(seconds)
                    results.append({"result": "OK"})
                else:
                    results.append({"result": None})
            elif command[0] == "INCR":
                self.store[command[1]] += 1
                results.append({"result": self.store[command[1]]})
        return httpx.Response(200, json=results)


def _limiter(fake: FakeUpstash, now: float = 1_000.0) -> UpstashRateLimiter:
    return UpstashRateLimiter(
        "https://example.upstash.io",
        "token-123",
        transport=httpx.MockTransport(fake.handler),
        clock=lambda: now,
    )


def test_upstash_counter_is_shared_between_instances():
    fake = FakeUpstash()
    first, second = _limiter(fake), _limiter(fake)
    enforce_rate_limit(first, RULE, "203.0.113.5")
    enforce_rate_limit(second, RULE, "203.0.113.5")
    with pytest.raises(ApiError) as exc_info:
        enforce_rate_limit(first, RULE, "203.0.113.5")
    assert (exc_info.value.status_code, exc_info.value.code) == (429, "rate_limited")
    # 別の識別子は別カウント
    enforce_rate_limit(second, RULE, "198.51.100.7")


def test_upstash_request_sets_expiry_and_hashes_identifier():
    fake = FakeUpstash()
    _limiter(fake).hit(RULE, "user@example.com")
    request = fake.requests[0]
    assert request.headers["authorization"] == "Bearer token-123"
    body = request.content.decode()
    assert "user@example.com" not in body
    commands = json.loads(body)
    assert commands[0][0] == "SET" and commands[0][3:] == ["EX", "60", "NX"]
    assert commands[1][0] == "INCR"
    assert list(fake.ttl.values()) == [60]


def test_upstash_window_resets():
    fake = FakeUpstash()
    assert _limiter(fake, now=1_000.0).hit(RULE, "ip") == 1
    assert _limiter(fake, now=1_019.0).hit(RULE, "ip") == 2
    assert _limiter(fake, now=1_020.0).hit(RULE, "ip") == 1  # 1020 // 60 = 17 → 新しいウィンドウ


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": "WRONGPASS invalid password"}),
        httpx.Response(400, json={"error": "ERR max daily request limit exceeded"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[{"result": "OK"}, {"error": "ERR value is not an int"}]),
    ],
)
def test_upstash_failure_is_503_not_allowed(response):
    limiter = UpstashRateLimiter(
        "https://example.upstash.io", "t", transport=httpx.MockTransport(lambda request: response)
    )
    with pytest.raises(ApiError) as exc_info:
        limiter.hit(RULE, "ip")
    assert (exc_info.value.status_code, exc_info.value.code) == (503, "service_unavailable")


def test_upstash_connection_error_is_503():
    def handler(request):
        raise httpx.ConnectError("down")

    limiter = UpstashRateLimiter("https://example.upstash.io", "t", transport=httpx.MockTransport(handler))
    with pytest.raises(ApiError) as exc_info:
        limiter.hit(RULE, "ip")
    assert exc_info.value.status_code == 503


def test_memory_limiter_for_local_use():
    limiter = MemoryRateLimiter(clock=lambda: 0.0)
    enforce_rate_limit(limiter, RULE, "ip")
    enforce_rate_limit(limiter, RULE, "ip")
    with pytest.raises(ApiError):
        enforce_rate_limit(limiter, RULE, "ip")
