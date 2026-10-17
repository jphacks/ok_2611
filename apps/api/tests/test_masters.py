import pytest

from tests.conftest import make_api_error

VALIDATION_ERROR = {"error": {"code": "validation_error", "message": "The request is invalid."}}


def test_allergens_returns_29_items_in_display_order(client, fake_supabase):
    response = client.get("/api/v1/allergens")
    assert response.status_code == 200
    items = response.json()["allergens"]
    assert len(items) == 29
    assert [item["display_order"] for item in items] == list(range(1, 30))
    assert [item["id"] for item in items[:9]] == [1, 2, 3, 6, 7, 4, 5, 8, 11]
    assert sum(item["category"] == "required" for item in items) == 9
    assert sum(item["category"] == "recommended" for item in items) == 20
    assert items[0] == {
        "id": 1,
        "code": "egg",
        "name": "卵",
        "name_en": "Egg",
        "display_name": "Egg",
        "category": "required",
        "display_order": 1,
    }
    assert all(item["display_name"] == item["name_en"] for item in items)
    # 並び順はDBに指定している
    assert ("order", "display_order", False) in fake_supabase.queries[0].calls


def test_dietary_restrictions_returns_4_items_in_id_order(client, fake_supabase):
    response = client.get("/api/v1/dietary-restrictions?locale=en")
    assert response.status_code == 200
    assert response.json() == {
        "dietary_restrictions": [
            {"id": 1, "code": "vegan", "name": "ヴィーガン", "display_name": "Vegan"},
            {"id": 2, "code": "vegetarian", "name": "ベジタリアン", "display_name": "Vegetarian"},
            {"id": 3, "code": "halal", "name": "ハラール", "display_name": "Halal"},
            {"id": 4, "code": "no_alcohol", "name": "アルコール不使用", "display_name": "No alcohol"},
        ]
    }
    assert ("order", "id", False) in fake_supabase.queries[0].calls


@pytest.mark.parametrize("path", ["/api/v1/allergens", "/api/v1/dietary-restrictions"])
@pytest.mark.parametrize("query", ["locale=ja", "locale=", "locale=EN", "foo=bar", "locale=en&extra=1"])
def test_masters_reject_invalid_locale_and_extra_query(client, path, query):
    response = client.get(f"{path}?{query}")
    assert response.status_code == 422
    assert response.json() == VALIDATION_ERROR
    assert response.headers["cache-control"] == "no-store"


def test_validation_error_does_not_echo_input(client):
    marker = "INJECTED_VALUE_<script>"
    response = client.get(f"/api/v1/allergens?locale={marker}")
    assert response.status_code == 422
    assert marker not in response.text


def test_master_db_error_is_converted(client, fake_supabase):
    fake_supabase.error = make_api_error("42501", "permission denied for table allergens")
    response = client.get("/api/v1/allergens")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "An unexpected error occurred."}}
    assert "permission" not in response.text


def test_master_wrong_row_count_is_internal_error(client, fake_supabase):
    fake_supabase.tables["dietary_restrictions"] = fake_supabase.tables["dietary_restrictions"][:3]
    response = client.get("/api/v1/dietary-restrictions")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def test_masters_unconfigured_supabase_is_503(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    response = TestClient(create_app(settings)).get("/api/v1/allergens")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
