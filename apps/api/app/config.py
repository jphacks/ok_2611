"""環境変数の読み込み。

`.env` は作業ディレクトリに依存せず `apps/api/.env` を明示的に読む。秘密値は `SecretStr` で保持し、
repr・ログ・レスポンスに出さない。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = API_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    supabase_url: str | None = None
    supabase_secret_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    google_maps_server_api_key: SecretStr | None = None

    # カンマ区切りのフロントURL。空なら全オリジンを拒否する。
    allowed_origins: str = ""

    # 店員回答の半減期（日）。食品情報の有効期限を意味しない（仮設定）
    store_answer_half_life_days: float = Field(default=30.0, gt=0)

    auth_jwt_secret: SecretStr | None = None
    account_token_ttl_hours: int = 24

    # レート制限の保存先。memory はローカル・テスト専用（Vercel上では起動時に拒否）。
    rate_limit_backend: Literal["memory", "upstash"] = "memory"
    upstash_redis_rest_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("UPSTASH_REDIS_REST_URL", "KV_REST_API_URL"),
    )
    upstash_redis_rest_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_TOKEN"),
    )

    # Vercelが実行環境に設定する（VERCEL=1）。
    vercel: bool = False

    @field_validator("supabase_url")
    @classmethod
    def _check_supabase_url(cls, value: str | None) -> str | None:
        if not value:
            return None
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("SUPABASE_URL must be an http(s) URL")
        if parts.path not in ("", "/") or parts.query or parts.fragment:
            # SDKが /rest/v1/ などを付けるため、パス付きのURLは誤設定
            raise ValueError("SUPABASE_URL must not include a path such as /rest/v1/")
        return value.rstrip("/")

    @field_validator("allowed_origins")
    @classmethod
    def _check_allowed_origins(cls, value: str) -> str:
        for origin in _split_csv(value):
            if origin == "*":
                raise ValueError("ALLOWED_ORIGINS must list explicit origins, not '*'")
            parts = urlsplit(origin)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.path not in ("", "/"):
                raise ValueError("ALLOWED_ORIGINS entries must be origins like https://example.com")
        return value

    @model_validator(mode="after")
    def _check_rate_limit_backend(self) -> "Settings":
        if self.rate_limit_backend == "memory" and self.vercel:
            raise ValueError("RATE_LIMIT_BACKEND=memory cannot be shared across Vercel instances")
        if self.rate_limit_backend == "upstash" and not (
            self.upstash_redis_rest_url and self.upstash_redis_rest_token
        ):
            raise ValueError("UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are required")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [origin.rstrip("/") for origin in _split_csv(self.allowed_origins)]


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class SettingsError(RuntimeError):
    """設定の誤り。メッセージは項目名と理由だけで、入力値（秘密値を含みうる）を含めない。"""


def load_settings() -> Settings:
    """環境変数・`.env` から設定を読む。

    pydantic の ValidationError の文字列は入力値（`input_value`）を含み、モデル全体の検証では
    `SUPABASE_SECRET_KEY` などの秘密値がそのまま起動時のログ（Vercelの関数ログ）に出る。
    そのため項目名と理由だけの例外に置き換え、元の例外も連鎖させない。
    """
    try:
        return Settings()
    except ValidationError as exc:
        reasons = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'settings'}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False, include_context=False)
        )
        raise SettingsError(f"invalid settings: {reasons}") from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
