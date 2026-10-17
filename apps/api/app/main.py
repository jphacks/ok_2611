"""FastAPI本体。Vercelは `app/main.py` の `app` を読み込む。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.errors import register_exception_handlers, unhandled_error_middleware
from app.log_filters import install_log_filters
from app.routers import confirmations, health, masters, menus, places

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    install_log_filters()

    app = FastAPI(title="Meelyze+ API", version="0.1.0")
    app.dependency_overrides[get_settings] = lambda: settings

    register_exception_handlers(app)
    # 追加した順に内側になる。想定外の例外を500にしてからCORSヘッダーを付ける。
    app.middleware("http")(unhandled_error_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
        max_age=600,
    )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(masters.router, prefix=API_PREFIX)
    app.include_router(places.router, prefix=API_PREFIX)
    app.include_router(menus.router, prefix=API_PREFIX)
    app.include_router(confirmations.router, prefix=API_PREFIX)
    return app


app = create_app()
