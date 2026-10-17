import pytest
from fastapi import APIRouter

from app.services.db_errors import translate_db_error
from tests.conftest import make_api_error


@pytest.mark.parametrize(
    ("sqlstate", "message", "details", "expected"),
    [
        ("28000", "invalid_analysis_token", None, (401, "invalid_analysis_token")),
        ("P0002", "menu_not_found", None, (404, "not_found")),
        ("P0002", "account_not_found", None, (401, "unauthorized")),
        ("P0003", "analysis_expired", None, (410, "analysis_expired")),
        ("40001", "request_id_conflict", None, (409, "request_id_conflict")),
        ("22023", "answers_invalid", None, (422, "answers_invalid")),
        ("22023", "dish_not_in_menu", None, (422, "dish_not_in_menu")),
        ("22023", "confirmation_limit_reached", None, (422, "confirmation_limit_reached")),
        ("22023", "invalid_allergen_ids", None, (422, "invalid_allergen_ids")),
        ("22023", "invalid_dietary_restriction_ids", None, (422, "invalid_dietary_restriction_ids")),
        ("22023", "validation_error", None, (422, "validation_error")),
        ("22023", "restaurant_mismatch", None, (422, "validation_error")),
        ("22023", "dish_version_mismatch", None, (422, "validation_error")),
        ("22023", "dishes_invalid", None, (422, "validation_error")),
        ("22023", "invalid_analysis_token_hash", None, (422, "validation_error")),
        (
            "23505",
            'duplicate key value violates unique constraint "accounts_email_key"',
            "Key (email)=(a@example.com) already exists.",
            (409, "email_already_registered"),
        ),
        (
            "23505",
            'duplicate key value violates unique constraint "restaurants_google_place_id_key"',
            None,
            (409, "conflict"),
        ),
        ("23502", "null value in column", None, (422, "validation_error")),
        ("23503", "violates foreign key constraint", None, (422, "validation_error")),
        ("23514", "violates check constraint", None, (422, "validation_error")),
        ("42501", "permission denied", None, (500, "internal_error")),
        ("55000", "snapshot_is_immutable", None, (500, "internal_error")),
        ("XX000", "boom", None, (500, "internal_error")),
        (None, None, None, (500, "internal_error")),
    ],
)
def test_translate_db_error(sqlstate, message, details, expected):
    mapping = translate_db_error(make_api_error(sqlstate, message, details))
    assert (mapping.status_code, mapping.code) == expected


def test_db_error_response_ignores_postgrest_status_and_hides_sql(app, client, caplog):
    router = APIRouter()

    @router.get("/api/v1/_test/db-error")
    def raise_db_error():
        # PostgRESTはP0002を500で返すが、APIはSQLSTATEとmessageだけで404にする
        raise make_api_error("P0002", "menu_not_found", "Key (token)=(secret-token) not found")

    app.include_router(router)
    with caplog.at_level("DEBUG"):
        response = client.get("/api/v1/_test/db-error?lat=35.6&lng=139.7")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "The resource was not found."}}
    assert response.headers["cache-control"] == "no-store"
    assert "secret-token" not in response.text
    assert "secret-token" not in caplog.text
    assert "35.6" not in caplog.text
    assert "sqlstate=P0002" in caplog.text
