"""06の純粋な処理（入力の正規化・カーソル・トークン・ログイン失敗の数え方）。DBはモック。

登録・ログイン・本人設定・本人履歴の実際の動作は tests/integration/test_accounts_local_db.py で確認する。
"""

import base64
import json
import time
import uuid

import httpx
import jwt
import pytest

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.routers import auth as auth_router
from app.services import auth as auth_service
from app.services.history import decode_cursor, encode_cursor
from app.services.rate_limit import MemoryRateLimiter, RateLimitRule, UpstashRateLimiter, get_rate_limiter
from app.services.supabase_client import get_supabase_client
from fastapi.testclient import TestClient
from tests.conftest import FRONT_ORIGIN

SECRET = "unit-test-jwt-secret-0123456789abcdef"


@pytest.mark.parametrize(
    ("email", "nickname", "password"),
    [
        ("not-an-email", "Alex", "password123"),
        ("a@b", "Alex", "password123"),
        ("x" * 250 + "@example.com", "Alex", "password123"),
        ("alex@example.com", "", "password123"),
        ("alex@example.com", "x" * 31, "password123"),
        ("alex@example.com", "Al\nex", "password123"),
        ("alex@example.com", "Alex", "short"),
        ("alex@example.com", "Alex", "x" * 129),
        ("alex@example.com", "Alex", "ALEX@example.com"),
    ],
)
def test_registration_validation(email, nickname, password):
    with pytest.raises(ApiError) as caught:
        auth_service.validate_registration(email, nickname, password)
    assert caught.value.code == "validation_error"


def test_registration_normalization_keeps_password_spaces():
    assert auth_service.validate_registration("  Alex@Example.COM ", "  Alex  ", " pass word ") == ("alex@example.com", "Alex")


def test_cursor_round_trip_and_rejects_tampering():
    menu_id = str(uuid.uuid4())
    cursor = encode_cursor("2026-10-17T03:00:00.123456+00:00", menu_id)
    assert decode_cursor(cursor) == ("2026-10-17T03:00:00.123456+00:00", menu_id)
    bad_payloads = [
        {"t": "2026-10-17T03:00:00", "id": menu_id},  # タイムゾーンなし
        {"t": "x", "id": menu_id},
        {"t": "2026-10-17T03:00:00+00:00", "id": "1) or (1=1"},
        {"t": "2026-10-17T03:00:00+00:00", "id": menu_id, "account_id": "x"},
        [],
    ]
    for payload in bad_payloads:
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        with pytest.raises(ApiError):
            decode_cursor(raw)
    with pytest.raises(ApiError):
        decode_cursor("%%%")


def test_issue_token_claims_and_secret_length():
    settings = Settings(_env_file=None, auth_jwt_secret=SECRET)
    issued = auth_service.issue_account_token("11111111-1111-4111-8111-111111111111", settings)
    claims = jwt.decode(issued.token, SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "iat", "exp", "typ"}
    assert claims["exp"] - claims["iat"] == 24 * 3600
    assert int(issued.expires_at.timestamp()) == claims["exp"]
    with pytest.raises(ApiError) as caught:
        auth_service.issue_account_token("x", Settings(_env_file=None, auth_jwt_secret="too-short"))
    assert caught.value.status_code == 503


def test_memory_count_does_not_increment():
    limiter = MemoryRateLimiter()
    rule = RateLimitRule("t", 5, 60)
    assert limiter.count(rule, "ip") == 0
    limiter.hit(rule, "ip")
    assert limiter.count(rule, "ip") == limiter.count(rule, "ip") == 1


@pytest.mark.parametrize(("result", "expected"), [("3", 3), (None, 0)])
def test_upstash_count(result, expected):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"result": result})

    limiter = UpstashRateLimiter("https://upstash.example", "token", transport=httpx.MockTransport(handler))
    assert limiter.count(RateLimitRule("t", 5, 60), "203.0.113.1") == expected
    assert requests[0][0] == "GET" and "203.0.113.1" not in requests[0][1]  # 識別子はハッシュ


def test_upstash_count_failure_is_503():
    limiter = UpstashRateLimiter(
        "https://upstash.example", "token", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    with pytest.raises(ApiError) as caught:
        limiter.count(RateLimitRule("t", 5, 60), "ip")
    assert caught.value.status_code == 503


@pytest.fixture
def login_client(fake_supabase, monkeypatch):
    app = create_app(Settings(_env_file=None, allowed_origins=FRONT_ORIGIN, auth_jwt_secret=SECRET))
    limiter = MemoryRateLimiter()
    app.dependency_overrides[get_supabase_client] = lambda: fake_supabase
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    calls = []

    def fake_authenticate(db, *, email, password):
        calls.append(email)
        return None

    monkeypatch.setattr(auth_router.auth_service, "authenticate", fake_authenticate)
    client = TestClient(app, raise_server_exceptions=False)
    client.calls = calls
    return client


def test_login_counts_only_failures_and_locks_per_email(login_client):
    for _ in range(5):
        response = login_client.post("/api/v1/auth/login", json={"email": "Alex@Example.com", "password": "wrong-pass"})
        assert response.json()["error"]["code"] == "invalid_credentials"
    locked = login_client.post("/api/v1/auth/login", json={"email": "alex@example.com", "password": "right-pass"})
    assert (locked.status_code, locked.json()["error"]["code"]) == (429, "rate_limited")
    assert len(login_client.calls) == 5  # 上限を超えたら照合しない
    assert login_client.calls[0] == "alex@example.com"


def test_login_body_validation(login_client):
    for body in ({"email": "a@example.com"}, {"email": "a@example.com", "password": 1}, {"email": "a@example.com", "password": "x", "extra": 1}):
        assert login_client.post("/api/v1/auth/login", json=body).status_code == 422
    assert login_client.calls == []


def test_verify_rejects_tokens(fake_supabase):
    settings = Settings(_env_file=None, auth_jwt_secret=SECRET)
    account_id = "11111111-1111-4111-8111-111111111111"
    fake_supabase.tables["accounts"] = [{"id": account_id}]
    good = auth_service.issue_account_token(account_id, settings).token
    assert auth_service.verify_account_token(good, settings, fake_supabase) == account_id
    now = int(time.time())
    for token, code in [
        (jwt.encode({"sub": account_id, "iat": now, "exp": now - 1, "typ": "account"}, SECRET, "HS256"), "account_token_expired"),
        (jwt.encode({"sub": account_id, "iat": now, "exp": now + 60, "typ": "account"}, SECRET, "HS384"), "unauthorized"),
        (jwt.encode({"sub": account_id, "iat": now, "exp": now + 60}, SECRET, "HS256"), "unauthorized"),
        (jwt.encode({"sub": account_id, "iat": now, "exp": now + 60, "typ": "account"}, "x" * 40, "HS256"), "unauthorized"),
    ]:
        with pytest.raises(ApiError) as caught:
            auth_service.verify_account_token(token, settings, fake_supabase)
        assert caught.value.code == code


def test_login_does_not_log_email_or_password(login_client, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        login_client.post("/api/v1/auth/login", json={"email": "secret.person@example.com", "password": "hunter2-password"})
    assert "secret.person" not in caplog.text and "hunter2" not in caplog.text
