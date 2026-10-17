import pytest
from pydantic import ValidationError

from app.config import ENV_FILE, Settings


def test_env_file_path_is_explicit():
    assert ENV_FILE.name == ".env"
    assert ENV_FILE.parent.name == "api"


def test_secrets_are_hidden_in_repr():
    settings = Settings(_env_file=None, supabase_secret_key="sb_secret_abc", auth_jwt_secret="jwt-secret")
    assert "sb_secret_abc" not in repr(settings)
    assert "jwt-secret" not in str(settings.model_dump())


def test_supabase_url_without_path(monkeypatch):
    assert Settings(_env_file=None, supabase_url="http://127.0.0.1:54321/").supabase_url == "http://127.0.0.1:54321"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, supabase_url="https://abc.supabase.co/rest/v1/")


@pytest.mark.parametrize("value", ["*", "localhost:8081", "https://example.com/app"])
def test_allowed_origins_rejects_wildcard_and_non_origins(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, allowed_origins=value)


def test_allowed_origins_parsing():
    settings = Settings(_env_file=None, allowed_origins=" http://localhost:8081, https://app.example.com/ ,")
    assert settings.cors_origins == ["http://localhost:8081", "https://app.example.com"]


def test_memory_rate_limit_is_rejected_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_upstash_requires_url_and_token(monkeypatch):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rate_limit_backend="upstash")
    # Vercel Marketplace の Upstash 連携が設定する名前でも読める
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "upstash")
    monkeypatch.setenv("KV_REST_API_URL", "https://example.upstash.io")
    monkeypatch.setenv("KV_REST_API_TOKEN", "token")
    settings = Settings(_env_file=None)
    assert settings.upstash_redis_rest_url == "https://example.upstash.io"
