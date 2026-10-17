"""CORS・共通エラー・Cache-Control・ログの基盤。"""

import logging

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import no_store
from app.errors import ApiError
from app.log_filters import AccessLogSanitizer
from app.schemas.common import StrictModel
from tests.conftest import FRONT_ORIGIN


def _add_test_routes(app):
    router = APIRouter(prefix="/api/v1/_test")

    class Body(StrictModel):
        name: str

    @router.post("/strict", dependencies=[Depends(no_store)])
    def strict(body: Body) -> dict:
        return {"name": body.name}

    @router.get("/api-error")
    def api_error():
        raise ApiError(410, "analysis_expired")

    @router.get("/crash")
    def crash():
        raise RuntimeError("Bearer secret-token lat=35.6812")

    @router.get("/upstream")
    def upstream():
        raise httpx.ConnectError("https://places.googleapis.com/?key=AIza-secret&lat=35.6812")

    @router.get("/timeout")
    def timeout():
        raise httpx.ReadTimeout("timed out")

    app.include_router(router)


def test_cors_allows_configured_origin(client):
    response = client.options(
        "/api/v1/allergens",
        headers={
            "Origin": FRONT_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONT_ORIGIN
    assert "access-control-allow-credentials" not in response.headers

    response = client.get("/api/v1/health", headers={"Origin": FRONT_ORIGIN})
    assert response.headers["access-control-allow-origin"] == FRONT_ORIGIN


def test_cors_rejects_other_origin(client):
    response = client.options(
        "/api/v1/allergens",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers

    response = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_extra_body_field_is_rejected_with_common_format(app, client):
    _add_test_routes(app)
    response = client.post("/api/v1/_test/strict", json={"name": "a", "account_id": "x"})
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "message": "The request is invalid."}}
    assert "account_id" not in response.text


def test_no_store_dependency_sets_header(app, client):
    _add_test_routes(app)
    response = client.post("/api/v1/_test/strict", json={"name": "a"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    # マスタ・healthには付けない（契約で指定がない）
    assert "cache-control" not in client.get("/api/v1/health").headers


def test_api_error_uses_common_format(app, client):
    _add_test_routes(app)
    response = client.get("/api/v1/_test/api-error")
    assert response.status_code == 410
    assert response.json() == {
        "error": {"code": "analysis_expired", "message": "The analysis has expired. Please take a new photo."}
    }
    assert response.headers["cache-control"] == "no-store"


def test_unhandled_error_is_500_without_details_and_keeps_cors(app, client, caplog):
    _add_test_routes(app)
    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/v1/_test/crash", headers={"Origin": FRONT_ORIGIN})
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "An unexpected error occurred."}}
    assert response.headers["access-control-allow-origin"] == FRONT_ORIGIN
    assert "secret-token" not in response.text
    assert "secret-token" not in caplog.text
    assert "35.6812" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_upstream_errors_hide_urls(app, client, caplog):
    _add_test_routes(app)
    with caplog.at_level(logging.DEBUG):
        unavailable = client.get("/api/v1/_test/upstream")
        timed_out = client.get("/api/v1/_test/timeout")
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "service_unavailable"
    assert timed_out.status_code == 504
    assert timed_out.json()["error"]["code"] == "timeout"
    for text in (unavailable.text, caplog.text):
        assert "AIza-secret" not in text
        assert "35.6812" not in text


def test_method_not_allowed_uses_common_format(client):
    response = client.post("/api/v1/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_access_log_strips_query_and_client_address():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("203.0.113.5:5000", "GET", "/api/v1/places/nearby?lat=35.6812&lng=139.7671", "1.1", 200),
        None,
    )
    assert AccessLogSanitizer().filter(record)
    message = record.getMessage()
    assert "35.6812" not in message
    assert "203.0.113.5" not in message
    assert "/api/v1/places/nearby" in message


def test_access_log_filter_is_installed(app):
    assert any(isinstance(f, AccessLogSanitizer) for f in logging.getLogger("uvicorn.access").filters)


def test_openapi_documents_common_error_format(app):
    schema = app.openapi()
    for path in ("/api/v1/health", "/api/v1/allergens", "/api/v1/dietary-restrictions"):
        content = schema["paths"][path]["get"]["responses"]["422"]["content"]["application/json"]
        assert content["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}
    ops = {path: item["get"]["operationId"] for path, item in schema["paths"].items() if "get" in item}
    assert ops.items() >= {
        "/api/v1/health": "get_health",
        "/api/v1/allergens": "get_allergens",
        "/api/v1/dietary-restrictions": "get_dietary_restrictions",
    }.items()
