"""API 3 `GET /places/nearby` と Place ID の存在確認（Googleはモック）。"""

import json
import logging

import httpx
import pytest

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.services import places as places_service
from app.services.places import PlacesClient, distance_m, get_places_client, verify_place_exists
from app.services.rate_limit import MemoryRateLimiter, get_rate_limiter
from app.services.supabase_client import get_supabase_client

LAT, LNG = 35.6812, 139.7671  # 東京駅付近（テスト用の公開地点）
NEARBY = f"/api/v1/places/nearby?lat={LAT}&lng={LNG}"


def google_place(place_id: str, lat: float, lng: float, name: str = "Soba Dining", address: str = "1-1 Marunouchi"):
    return {
        "id": place_id,
        "displayName": {"text": name, "languageCode": "en"},
        "location": {"latitude": lat, "longitude": lng},
        "shortFormattedAddress": address,
        "formattedAddress": f"{address}, Tokyo, Japan",
    }


class FakeGoogle:
    def __init__(self) -> None:
        self.places: list[dict] = []
        self.nearby_status = 200
        self.nearby_body: object | None = None
        self.details: dict[str, int] = {}
        self.error: Exception | None = None
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if request.url.path == "/v1/places:searchNearby":
            if self.nearby_body is not None:
                return httpx.Response(self.nearby_status, json=self.nearby_body)
            body = {"places": self.places} if self.places else {}
            return httpx.Response(self.nearby_status, json=body)
        place_id = request.url.path.removeprefix("/v1/places/")
        status = self.details.get(place_id, 404)
        if status == 200:
            return httpx.Response(200, json={"id": place_id})
        return httpx.Response(status, json={"error": {"code": status, "status": "NOT_FOUND"}})


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def places_client(google) -> PlacesClient:
    return PlacesClient("AIza-test-secret", transport=httpx.MockTransport(google.handler))


@pytest.fixture
def limiter() -> MemoryRateLimiter:
    return MemoryRateLimiter()


@pytest.fixture
def app(settings, fake_supabase, places_client, limiter):
    app = create_app(settings)
    app.dependency_overrides[get_supabase_client] = lambda: fake_supabase
    app.dependency_overrides[get_places_client] = lambda: places_client
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return app


def published(place_id: str, menu_id: str, dish_id: str, name_key: str) -> dict:
    return {"google_place_id": place_id, "menu_id": menu_id, "dish_id": dish_id, "name_key": name_key}


def test_nearby_returns_places_sorted_by_distance_with_public_counts(client, google, fake_supabase):
    google.places = [
        google_place("far_place", 35.6840, 139.7671, name="Far"),
        google_place("near_place", 35.6815, 139.7668, name="Near"),
        google_place("mid_place", 35.6825, 139.7671, name="Mid"),
    ]
    fake_supabase.tables["published_menus"] = [
        # 料理数は name_key の種類数。別のメニュー（m2）の同じ料理は重ねて数えない
        published("near_place", "m1", "d1", "kakesoba"),
        published("near_place", "m1", "d2", "tempurasoba"),
        published("near_place", "m1", "d5", "curry"),
        published("near_place", "m2", "d3", "kakesoba"),
        published("other_place", "m3", "d4", "udon"),
    ]
    response = client.get(NEARBY)
    assert response.status_code == 200
    body = response.json()
    assert body["attribution"] == "Google Maps"
    assert [p["google_place_id"] for p in body["places"]] == ["near_place", "mid_place", "far_place"]
    near = body["places"][0]
    assert near == {
        "google_place_id": "near_place",
        "name": "Near",
        "latitude": 35.6815,
        "longitude": 139.7668,
        "address": "1-1 Marunouchi",
        "distance_m": distance_m(LAT, LNG, 35.6815, 139.7668),
        "has_public_menus": True,
        "public_menu_count": 3,  # 行数4・メニュー数2ではなく name_key の種類数
    }
    assert body["places"][1]["has_public_menus"] is False
    assert body["places"][1]["public_menu_count"] == 0
    assert response.headers["cache-control"] == "no-store"
    # 公開ビューだけを読み、基礎テーブルは読まない
    assert {q.table for q in fake_supabase.queries} == {"published_menus"}


def test_nearby_request_to_google(client, google):
    client.get(f"{NEARBY}&radius_m=500&locale=en")
    request = google.requests[0]
    assert request.method == "POST"
    assert request.headers["x-goog-api-key"] == "AIza-test-secret"
    assert "key=" not in str(request.url)
    assert request.headers["x-goog-fieldmask"] == (
        "places.id,places.displayName,places.location,places.shortFormattedAddress,places.formattedAddress"
    )
    body = json.loads(request.content)
    assert body == {
        "includedTypes": ["restaurant"],
        "maxResultCount": 20,
        "rankPreference": "DISTANCE",
        "languageCode": "en",
        "locationRestriction": {"circle": {"center": {"latitude": LAT, "longitude": LNG}, "radius": 500.0}},
    }


def test_nearby_default_radius_is_300(client, google):
    client.get(NEARBY)
    assert json.loads(google.requests[0].content)["locationRestriction"]["circle"]["radius"] == 300.0


def test_nearby_zero_results(client, google, fake_supabase):
    response = client.get(NEARBY)
    assert response.status_code == 200
    assert response.json() == {"places": [], "attribution": "Google Maps"}
    assert fake_supabase.queries == []


def test_nearby_limits_to_20_and_dedupes(client, google):
    google.places = [google_place(f"p{i:02d}", LAT + i * 0.0001, LNG) for i in range(25)]
    google.places.append(google_place("p00", LAT + 0.01, LNG))
    body = client.get(NEARBY).json()
    ids = [p["google_place_id"] for p in body["places"]]
    assert len(ids) == 20 and len(set(ids)) == 20
    assert ids[0] == "p00"
    assert body["places"][0]["distance_m"] == 0


def test_nearby_skips_malformed_google_items(client, google):
    google.places = [
        google_place("ok", LAT, LNG),
        {"id": "no_location"},
        {"location": {"latitude": LAT, "longitude": LNG}},
        google_place("bad/id", LAT, LNG),
        {"id": "no_name", "location": {"latitude": LAT, "longitude": LNG}},
    ]
    body = client.get(NEARBY).json()
    # 同じ距離ならPlace IDの昇順
    assert [p["google_place_id"] for p in body["places"]] == ["no_name", "ok"]
    assert body["places"][0]["name"] == "" and body["places"][0]["address"] == ""


@pytest.mark.parametrize(
    "query",
    [
        "lat=90.1&lng=0",
        "lat=-90.1&lng=0",
        "lat=0&lng=180.1",
        "lat=0&lng=-180.1",
        "lat=nan&lng=0",
        "lat=0&lng=inf",
        "lng=0",
        "lat=0",
        "lat=abc&lng=0",
        "lat=0&lng=0&radius_m=49",
        "lat=0&lng=0&radius_m=1001",
        "lat=0&lng=0&radius_m=300.5",
        "lat=0&lng=0&locale=ja",
        "lat=0&lng=0&type=bar",
    ],
)
def test_nearby_rejects_invalid_query_without_calling_google(client, google, query):
    response = client.get(f"/api/v1/places/nearby?{query}")
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "validation_error", "message": "The request is invalid."}}
    assert google.requests == []


def test_nearby_accepts_boundary_values(client, google):
    for query in ("lat=90&lng=180&radius_m=50", "lat=-90&lng=-180&radius_m=1000"):
        assert client.get(f"/api/v1/places/nearby?{query}").status_code == 200


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_nearby_google_error_is_503(client, google, status, caplog):
    google.nearby_status = status
    google.nearby_body = {"error": {"message": "API key AIza-test-secret invalid"}}
    with caplog.at_level(logging.DEBUG):
        response = client.get(NEARBY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "AIza" not in response.text and "AIza" not in caplog.text


@pytest.mark.parametrize("error", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
def test_nearby_google_connection_failure_is_503(client, google, error, caplog):
    google.error = error
    with caplog.at_level(logging.DEBUG):
        response = client.get(NEARBY)
    assert response.status_code == 503
    assert str(LAT) not in caplog.text


def test_nearby_invalid_google_json_is_503(client, google):
    google.nearby_body = {"places": "not-a-list"}
    assert client.get(NEARBY).status_code == 503


def test_nearby_rate_limited_after_30_per_minute(client, google):
    for _ in range(30):
        assert client.get(NEARBY).status_code == 200
    response = client.get(NEARBY)
    assert response.status_code == 429
    assert response.json() == {"error": {"code": "rate_limited", "message": "Too many requests. Please try again later."}}
    assert len(google.requests) == 30  # 上限を超えた分はGoogleを呼ばない


def test_rate_limit_uses_vercel_header_only_on_vercel(settings, fake_supabase, places_client, monkeypatch):
    from fastapi.testclient import TestClient

    limiter = MemoryRateLimiter()
    seen: list[str] = []
    original = limiter.hit

    def hit(rule, identifier):
        seen.append(identifier)
        return original(rule, identifier)

    limiter.hit = hit
    for on_vercel in (False, True):
        monkeypatch.setenv("VERCEL", "1" if on_vercel else "0")
        s = Settings(_env_file=None, rate_limit_backend="upstash", upstash_redis_rest_url="https://x.upstash.io",
                     upstash_redis_rest_token="t") if on_vercel else settings
        app = create_app(s)
        app.dependency_overrides[get_supabase_client] = lambda: fake_supabase
        app.dependency_overrides[get_places_client] = lambda: places_client
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
        TestClient(app).get(NEARBY, headers={"x-vercel-forwarded-for": "203.0.113.9", "x-forwarded-for": "198.51.100.1"})
    assert seen == ["testclient", "203.0.113.9"]


def test_nearby_coordinates_not_logged(client, google, caplog):
    google.places = [google_place("near_place", 35.6815, 139.7668)]
    with caplog.at_level(logging.DEBUG):
        client.get(NEARBY)
    for value in ("35.6812", "139.7671", "35.6815", "Marunouchi", "Soba Dining"):
        assert value not in caplog.text


def test_nearby_unconfigured_key_is_503(settings, fake_supabase, limiter):
    from fastapi.testclient import TestClient

    app = create_app(settings)
    app.dependency_overrides[get_supabase_client] = lambda: fake_supabase
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    response = TestClient(app).get(NEARBY)
    assert response.status_code == 503


def test_nearby_does_not_write_google_data(client, google, fake_supabase):
    google.places = [google_place("near_place", 35.6815, 139.7668)]
    client.get(NEARBY)
    # FakeSupabase には insert/update/upsert がなく、呼べば AttributeError で500になる
    assert all(call[0] in ("select", "in", "order", "range") for q in fake_supabase.queries for call in q.calls)


# --- Place ID の存在確認（03で使う） ---


def test_verify_place_exists(places_client, google):
    google.details["ChIJ_ok"] = 200
    verify_place_exists(places_client, "ChIJ_ok")
    request = google.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/v1/places/ChIJ_ok"
    assert request.headers["x-goog-fieldmask"] == "id"


@pytest.mark.parametrize("status", [400, 404])
def test_verify_place_not_found(places_client, google, status):
    google.details["ChIJ_missing"] = status
    with pytest.raises(ApiError) as exc_info:
        verify_place_exists(places_client, "ChIJ_missing")
    assert (exc_info.value.status_code, exc_info.value.code) == (404, "place_not_found")


@pytest.mark.parametrize("place_id", ["", "a/b", "../x", "a b", "a?key=1", "x" * 256, "日本"])
def test_verify_malformed_place_id_is_not_sent(places_client, google, place_id):
    with pytest.raises(ApiError) as exc_info:
        verify_place_exists(places_client, place_id)
    assert exc_info.value.code == "place_not_found"
    assert google.requests == []


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_verify_place_google_error_is_503(places_client, google, status):
    google.details["ChIJ_x"] = status
    with pytest.raises(ApiError) as exc_info:
        verify_place_exists(places_client, "ChIJ_x")
    assert (exc_info.value.status_code, exc_info.value.code) == (503, "service_unavailable")


def test_verify_place_timeout_is_503(places_client, google):
    google.error = httpx.ReadTimeout("slow")
    with pytest.raises(ApiError) as exc_info:
        verify_place_exists(places_client, "ChIJ_x")
    assert exc_info.value.status_code == 503


def test_distance():
    assert distance_m(LAT, LNG, LAT, LNG) == 0
    # 緯度0.001度 ≒ 111m
    assert 110 <= distance_m(35.0, 139.0, 35.001, 139.0) <= 112


def test_openapi_documents_nearby(app):
    op = app.openapi()["paths"]["/api/v1/places/nearby"]["get"]
    assert op["operationId"] == "get_nearby_places"
    params = {p["name"]: p for p in op["parameters"]}
    assert set(params) == {"lat", "lng", "radius_m", "locale"}
    assert params["lat"]["required"] and params["lng"]["required"]
    assert {"200", "422", "429", "503"} <= set(op["responses"])
