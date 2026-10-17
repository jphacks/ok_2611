"""API 4 `POST /menus/analyze`・API 5 `GET /menus/{menu_id}`（Gemini・Google・DB・Storageはモック）。

実際のRPC・Storage・履歴クエリは tests/integration/test_menus_local_db.py（ローカルSupabase）で確認する。
"""

import hashlib
import io
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.errors import ApiError
from app.main import create_app
from app.services import menus as menu_store
from app.services.menu_analysis import get_menu_analyzer
from app.services.menus import DishRow, MenuAnswer, MenuRow, SavedConfirmation, StoreAnswerRow
from app.services.places import PlacesClient, get_optional_places_client
from app.services.rate_limit import MemoryRateLimiter, get_rate_limiter
from app.services.supabase_client import get_supabase_client
from tests.conftest import FRONT_ORIGIN, make_api_error

SECRET = "unit-test-jwt-secret-0123456789abcdef"
ACCOUNT_ID = "11111111-1111-4111-8111-111111111111"
PLACE = "ChIJN1t_tDeuEmsRUsoyG83frY4"
ANALYZE = "/api/v1/menus/analyze"


def jpeg(size=(32, 24)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, "JPEG")
    return buffer.getvalue()


def ai_dish(name: str, allergens=(), dietary=()) -> dict:
    return {
        "name": name,
        "translations": {"en": {"name": f"{name} (en)", "description": "AI description"}},
        "price": 1200,
        "currency": "JPY",
        "ingredients": [],
        "allergens": list(allergens),
        "dietary_restrictions": list(dietary),
    }


SHRIMP_EXPLICIT = {"allergen_id": 4, "status": "explicit_present", "source": "menu_text", "evidence": "海老天"}
BUCKWHEAT_POSSIBLE = {"allergen_id": 6, "status": "possible", "source": "dish_name_inference", "evidence": "Soba."}
MILK_UNKNOWN = {"allergen_id": 2, "status": "unknown", "source": "unavailable", "evidence": ""}
SAKE_POSSIBLE = {"dietary_restriction_id": 4, "status": "possible_conflict", "source": "recipe_inference", "evidence": "Mirin."}


class FakeAnalyzer:
    model = "gemini-test"

    def __init__(self) -> None:
        self.output: object = {
            "dishes": [
                ai_dish("海老天そば", [SHRIMP_EXPLICIT, BUCKWHEAT_POSSIBLE, MILK_UNKNOWN], [SAKE_POSSIBLE]),
                ai_dish("かけそば", [BUCKWHEAT_POSSIBLE]),
            ]
        }
        self.error: Exception | None = None
        self.calls: list[tuple] = []

    def analyze(self, image, allergens, dietary_restrictions):
        self.calls.append((image, allergens, dietary_restrictions))
        if self.error is not None:
            raise self.error
        return self.output


class FakeStore:
    """app.services.menus の関数を置き換えるインメモリの保存先。"""

    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.restaurants: dict[str, str] = {}
        self.uploaded: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []
        self.saved: dict[str, dict] = {}
        self.menus: dict[str, MenuRow] = {}
        self.dishes: dict[str, list[DishRow]] = {}
        self.menu_answers: dict[str, tuple[list[MenuAnswer], list[MenuAnswer]]] = {}
        self.store_allergen: list[StoreAnswerRow] = []
        self.store_dietary: list[StoreAnswerRow] = []
        self.history_calls: list[tuple] = []
        self.save_error: Exception | None = None
        self.confirm_calls: list[dict] = []
        self.confirm_error: Exception | None = None
        self.replayed = False
        self.user_publish_consent = False

    def install(self, monkeypatch) -> None:
        for name in (
            "get_or_create_restaurant", "upload_image", "delete_image", "save_menu_analysis", "get_menu",
            "list_dishes", "list_menu_answers", "list_store_allergen_answers", "list_store_dietary_answers",
            "complete_confirmation",
        ):
            monkeypatch.setattr(menu_store, name, getattr(self, name))

    def get_or_create_restaurant(self, client, google_place_id):
        return self.restaurants.setdefault(google_place_id, str(uuid.uuid4()))

    def upload_image(self, client, path, image):
        self.uploaded[path] = (image.data, image.content_type)

    def delete_image(self, client, path):
        self.deleted.append(path)

    def save_menu_analysis(self, client, **kwargs):
        if self.save_error is not None:
            raise self.save_error
        menu_id = str(uuid.uuid4())
        self.saved[menu_id] = kwargs
        place = next((p for p, r in self.restaurants.items() if r == kwargs["restaurant_id"]), None)
        self.menus[menu_id] = MenuRow(
            menu_id, kwargs["restaurant_id"], place, kwargs["token_hash"], self.now + timedelta(hours=24),
            # ゲストは常にfalse（RPCが登録時同意をコピーする）
            self.user_publish_consent if kwargs["account_id"] else False,
        )
        self.dishes[menu_id] = [
            DishRow(
                id=str(uuid.uuid4()), position=i + 1, version=1, ai_model=kwargs["ai_model"],
                prompt_version=kwargs["prompt_version"], analyzed_at=self.now, **{
                    key: payload[key] for key in ("name", "name_key", "translations", "price", "currency", "ai_result")
                },
            )
            for i, payload in enumerate(d.rpc_payload() for d in kwargs["dishes"])
        ]
        return menu_id

    def complete_confirmation(self, client, **kwargs):
        self.confirm_calls.append(kwargs)
        if self.confirm_error is not None:
            raise self.confirm_error
        return SavedConfirmation(str(uuid.uuid4()), self.now, self.replayed)

    def get_menu(self, client, menu_id):
        return self.menus.get(menu_id)

    def list_dishes(self, client, menu_id):
        return list(self.dishes.get(menu_id, []))

    def list_menu_answers(self, client, menu_id):
        return self.menu_answers.get(menu_id, ([], []))

    def list_store_allergen_answers(self, client, restaurant_id, name_keys, ids):
        self.history_calls.append(("allergen", restaurant_id, sorted(name_keys), list(ids)))
        return [r for r in self.store_allergen if r.name_key in name_keys and r.item_id in ids]

    def list_store_dietary_answers(self, client, restaurant_id, name_keys, ids):
        self.history_calls.append(("dietary", restaurant_id, sorted(name_keys), list(ids)))
        return [r for r in self.store_dietary if r.name_key in name_keys and r.item_id in ids]


class FakeGoogle:
    def __init__(self) -> None:
        self.status = 200
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.status == 200:
            return httpx.Response(200, json={"id": request.url.path.removeprefix("/v1/places/")})
        return httpx.Response(self.status, json={})


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, allowed_origins=FRONT_ORIGIN, auth_jwt_secret=SECRET)


@pytest.fixture
def analyzer() -> FakeAnalyzer:
    return FakeAnalyzer()


@pytest.fixture
def store(monkeypatch) -> FakeStore:
    fake = FakeStore()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def clock():
    return {"now": 1_000_000.0}


@pytest.fixture
def app(settings, fake_supabase, analyzer, store, google, clock):
    app = create_app(settings)
    limiter = MemoryRateLimiter(clock=lambda: clock["now"])
    places = PlacesClient("k", transport=httpx.MockTransport(google.handler))
    app.dependency_overrides[get_supabase_client] = lambda: fake_supabase
    app.dependency_overrides[get_menu_analyzer] = lambda: analyzer
    app.dependency_overrides[get_optional_places_client] = lambda: places
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return app


def analyze(client: TestClient, fields=None, files=None, headers=None):
    files = files if files is not None else [("image", ("menu.jpg", jpeg(), "image/jpeg"))]
    return client.post(ANALYZE, data=fields or {}, files=files, headers=headers or {})


def account_token(sub=ACCOUNT_ID, typ="account", exp_delta=600, secret=SECRET, **extra) -> str:
    now = int(time.time())
    claims = {"sub": sub, "iat": now, "exp": now + exp_delta, "typ": typ, **extra}
    return jwt.encode(claims, secret, "HS256")


def by_id(items, key):
    return {item[key]: item for item in items}


# --- API 4：正常系 ---


def test_analyze_guest_without_store(client, analyzer, store, google):
    response = analyze(client)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    token = body["analysis_token"]
    assert len(token) >= 43  # 256bit を URL-safe Base64 にしたもの
    saved = store.saved[body["menu_id"]]
    assert saved["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert saved["account_id"] is None and saved["restaurant_id"] is None
    assert saved["prompt_version"] == "v5" and saved["ai_model"] == "gemini-test"
    assert google.calls == 0  # 店舗未選択ではGoogleを呼ばない
    assert body["google_place_id"] is None
    assert body["prompt_version"] == "v5" and body["locale"] == "en"
    assert body["analyzed_at"].endswith("Z") and body["analysis_expires_at"].endswith("Z")
    assert "image_path" not in response.text and next(iter(store.uploaded)) not in response.text

    first, second = body["dishes"]
    assert (first["name"], first["display_name"], first["dish_version"]) == ("海老天そば", "海老天そば (en)", 1)
    # 対象省略時：AIが明示したアレルゲン（unknown も含む）をマスタの表示順（乳2番目・そば4番目・えび6番目）で
    assert [a["allergen_id"] for a in first["allergens"]] == [2, 6, 4]
    shrimp = by_id(first["allergens"], "allergen_id")[4]
    assert shrimp == {
        "allergen_id": 4,
        "display_name": "Shrimp",
        "ai": {"status": "explicit_present", "source": "menu_text", "evidence": "海老天", "weight": None},
        "current_answer": None,
        "store_history": None,
        "notices": {
            "ai_staff_mismatch": False, "recheck_current_answer": False,
            "history_conflict": False, "history_shared_utensils": False,
        },
    }
    assert first["dietary_restrictions"] == []  # 省略時は食事制限の予測なし
    assert [a["allergen_id"] for a in second["allergens"]] == [6]
    assert store.history_calls == []


def test_selected_ids_are_not_sent_to_gemini_or_saved(client, analyzer, store):
    response = analyze(client, {"allergen_ids": ["1", "4"], "dietary_restriction_ids": ["1", "4"]})
    assert response.status_code == 201
    [(image, allergens, dietary)] = analyzer.calls
    # Geminiへはマスタ全件だけ
    assert sorted(a.id for a in allergens) == list(range(1, 30))
    assert sorted(d.id for d in dietary) == [1, 2, 3, 4]
    saved = store.saved[response.json()["menu_id"]]
    # 保存する ai_result はAIの出力だけ（選択した卵1・Vegan1は含まない）
    stored = [d.ai_result() for d in saved["dishes"]]
    assert [a["allergen_id"] for a in stored[0]["allergens"]] == [2, 4, 6]
    assert [d["dietary_restriction_id"] for d in stored[0]["dietary_restrictions"]] == [4]
    assert "allergen_ids" not in json.dumps(saved, default=str)

    first = response.json()["dishes"][0]
    assert [a["allergen_id"] for a in first["allergens"]] == [1, 4]  # 卵（表示順1）→えび（6）
    egg = first["allergens"][0]
    assert egg["ai"] == {"status": "unknown", "source": "unavailable", "evidence": "", "weight": None}
    diets = by_id(first["dietary_restrictions"], "dietary_restriction_id")
    assert list(diets) == [1, 4]
    assert diets[1]["ai"]["status"] == "unknown"
    assert diets[4]["ai"] == {"status": "possible_conflict", "source": "recipe_inference", "evidence": "Mirin.", "weight": None}
    assert set(diets[4]["notices"]) == {"ai_staff_mismatch", "recheck_current_answer", "history_conflict", "history_cross_contact"}


def test_recorded_menu_returns_201_and_can_be_read_again(client, analyzer, store, okinawa_output):
    from tests.test_openapi_contract import response_schema, validate

    analyzer.output = okinawa_output
    response = analyze(client, {"dietary_restriction_ids": ["1", "2", "3", "4"]})
    assert response.status_code == 201, response.text
    body = response.json()
    validate(body, response_schema("/menus/analyze", "post", "201"))
    assert len(body["dishes"]) == 14
    assert [(d["name"], d["price"]) for d in body["dishes"]] == [
        (d["name"], d["price"]) for d in okinawa_output["dishes"]
    ]
    for index in (10, 11):
        diets = by_id(body["dishes"][index]["dietary_restrictions"], "dietary_restriction_id")
        for item_id in (3, 4):
            item = diets[item_id]
            assert item["ai"] == {"status": "unknown", "source": "unavailable", "evidence": "", "weight": None}
            assert item["current_answer"] is None and item["store_history"] is None
            assert not any(item["notices"].values())
    fetched = client.get(f"/api/v1/menus/{body['menu_id']}?dietary_restriction_ids=1,2,3,4",
                         headers={"Authorization": f"Bearer {body['analysis_token']}"})
    assert fetched.status_code == 200
    validate(fetched.json(), response_schema("/menus/{menu_id}", "get", "200"))
    assert fetched.json()["dishes"] == body["dishes"]
    assert len(analyzer.calls) == 1
    saved = [d.ai_result() for d in store.saved[body["menu_id"]]["dishes"]]
    assert sum(c["status"] == "unknown" for d in saved for c in d["dietary_restrictions"]) == 4


@pytest.mark.parametrize("selected", [False, True])
def test_all_unknown_is_success_and_explicit_unknown_stays_visible(client, analyzer, selected):
    analyzer.output = {"dishes": [ai_dish("読める料理", [
        {**SHRIMP_EXPLICIT, "source": "recipe_inference"}
    ], [{**SAKE_POSSIBLE, "evidence": "  "}])]}
    fields = {"dietary_restriction_ids": ["4"]}
    if selected:
        fields["allergen_ids"] = ["4", "1"]
    response = analyze(client, fields)
    assert response.status_code == 201, response.text
    body = response.json()
    first = body["dishes"][0]
    assert [a["allergen_id"] for a in first["allergens"]] == ([1, 4] if selected else [4])
    for item in first["allergens"] + first["dietary_restrictions"]:
        assert item["ai"] == {"status": "unknown", "source": "unavailable", "evidence": "", "weight": None}
        assert item["current_answer"] is None and item["store_history"] is None
    fetched = client.get(f"/api/v1/menus/{body['menu_id']}", headers={"Authorization": f"Bearer {body['analysis_token']}"})
    assert fetched.status_code == 200
    assert [a["allergen_id"] for a in fetched.json()["dishes"][0]["allergens"]] == [4]
    assert fetched.json()["dishes"][0]["dietary_restrictions"] == []


def test_invalid_saved_classification_is_not_returned_or_logged(client, store, caplog):
    body = analyze(client).json()
    candidate = store.dishes[body["menu_id"]][0].ai_result["allergens"][1]
    candidate.update(status="explicit_present", source="recipe_inference", evidence="private-invalid-evidence")
    response = client.get(f"/api/v1/menus/{body['menu_id']}", headers={"Authorization": f"Bearer {body['analysis_token']}"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private-invalid-evidence" not in response.text + caplog.text
    assert body["analysis_token"] not in response.text + caplog.text


def test_analyze_with_store_uses_history(client, store, google):
    restaurant = store.get_or_create_restaurant(None, PLACE)
    old = store.now - timedelta(days=30)
    store.store_allergen = [
        StoreAnswerRow("m1", "海老天そば", 4, "contains", store.now),
        StoreAnswerRow("m2", "海老天そば", 4, "does_not_contain", old),
        StoreAnswerRow("m3", "海老天そば", 4, "shared_utensils", old),
        StoreAnswerRow("m4", "海老天そば", 4, "unknown", old),
        StoreAnswerRow("m5", "かけそば", 4, "contains", store.now),  # 別の料理名
        StoreAnswerRow("m6", "海老天そば", 1, "contains", store.now),  # 別の項目
    ]
    store.store_dietary = [StoreAnswerRow("m1", "海老天そば", 4, "not_supported", store.now)]
    response = analyze(client, {"google_place_id": PLACE, "allergen_ids": ["4"], "dietary_restriction_ids": ["4"]})
    assert response.status_code == 201, response.text
    assert google.calls == 1
    body = response.json()
    assert body["google_place_id"] == PLACE
    assert store.saved[body["menu_id"]]["restaurant_id"] == restaurant
    assert ("allergen", restaurant, ["かけそば", "海老天そば"], [4]) in store.history_calls

    shrimp = body["dishes"][0]["allergens"][0]
    history = shrimp["store_history"]
    assert history["match_basis"] == "name_key"
    assert history["answer_counts"] == {"contains": 1, "shared_utensils": 1, "does_not_contain": 1, "unknown": 1}
    assert (history["alpha"], history["beta"]) == (2.0, 1.5)
    assert history["score"] == pytest.approx(2 / 3.5, abs=1e-3)
    assert history["has_conflict"] is True
    assert history["last_answered_at"]["shared_utensils"].endswith("Z")
    assert shrimp["current_answer"] is None
    assert shrimp["notices"]["history_conflict"] is True
    assert shrimp["notices"]["history_shared_utensils"] is True
    assert "safe" not in response.text.lower()

    diet = body["dishes"][0]["dietary_restrictions"][0]
    assert diet["store_history"]["answer_counts"] == {"not_supported": 1, "cross_contact": 0, "supported": 0, "unknown": 0}
    assert diet["store_history"]["score"] == pytest.approx(0.667)
    # 別の料理（かけそば）の えび は自分の料理名の回答だけ
    kake = body["dishes"][1]["allergens"][0]
    assert kake["store_history"]["answer_counts"]["contains"] == 1
    assert kake["store_history"]["has_conflict"] is False


# --- API 4：入力の検証 ---


@pytest.mark.parametrize(
    ("fields", "files"),
    [
        ({"account_id": ACCOUNT_ID}, None),  # 本文での所有者の指定
        ({"user_publish_consent": "true"}, None),  # 本文での利用者同意の指定
        ({"unknown": "1"}, None),
        ({"allergen_ids": "4,6"}, None),  # カンマ区切りのpart
        ({"allergen_ids": "[4, 6]"}, None),  # JSON配列の文字列
        ({"allergen_ids": "-1"}, None),
        ({"allergen_ids": ""}, None),
        ({"dietary_restriction_ids": "1.0"}, None),
        ({"locale": "ja"}, None),
        ({"locale": ["en", "en"]}, None),
        ({"google_place_id": [PLACE, PLACE]}, None),
        ({}, []),  # 画像なし
        ({}, [("image", ("a.jpg", jpeg(), "image/jpeg")), ("image", ("b.jpg", jpeg(), "image/jpeg"))]),
        ({"image": "not a file"}, []),
        ({}, [("image", ("a.jpg", jpeg(), "image/jpeg")), ("google_place_id", ("p.txt", b"x", "text/plain"))]),
    ],
)
def test_invalid_form_is_422(client, analyzer, store, fields, files):
    response = analyze(client, fields, files)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert analyzer.calls == [] and store.uploaded == {}


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"allergen_ids": ["4", "4"]}, "invalid_allergen_ids"),
        ({"allergen_ids": ["30"]}, "invalid_allergen_ids"),
        ({"allergen_ids": ["0"]}, "invalid_allergen_ids"),
        ({"dietary_restriction_ids": ["1", "1"]}, "invalid_dietary_restriction_ids"),
        ({"dietary_restriction_ids": ["5"]}, "invalid_dietary_restriction_ids"),
    ],
)
def test_unknown_or_duplicate_ids_are_422(client, analyzer, fields, code):
    response = analyze(client, fields)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert analyzer.calls == []


def test_non_multipart_body_is_422(client, analyzer):
    response = client.post(ANALYZE, json={"image": "x"})
    assert response.status_code == 422
    assert analyzer.calls == []


def test_image_type_and_size_errors(client, analyzer, monkeypatch):
    gif = io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    response = analyze(client, files=[("image", ("a.gif", gif.getvalue(), "image/gif"))])
    assert (response.status_code, response.json()["error"]["code"]) == (415, "unsupported_image_type")
    # MIMEだけをJPEGにしたPNG
    png = io.BytesIO()
    Image.new("RGB", (4, 4)).save(png, "PNG")
    response = analyze(client, files=[("image", ("a.jpg", png.getvalue(), "image/jpeg"))])
    assert response.status_code == 415
    # 2 MiB超過（本文の上限も超えるため読み込み中に止める）
    response = analyze(client, files=[("image", ("a.jpg", b"\xff\xd8\xff" + b"\0" * (3 * 1024 * 1024), "image/jpeg"))])
    assert (response.status_code, response.json()["error"]["code"]) == (413, "image_too_large")
    from app.services import images

    monkeypatch.setattr(images, "MAX_IMAGE_PIXELS", 100)
    response = analyze(client)
    assert (response.status_code, response.json()["error"]["code"]) == (413, "image_too_large")
    assert analyzer.calls == []


def test_uploaded_image_is_sanitized(client, store):
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "CameraMaker"
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buffer, "JPEG", exif=exif.tobytes())
    assert analyze(client, files=[("image", ("a.jpg", buffer.getvalue(), "image/jpeg"))]).status_code == 201
    [(data, content_type)] = store.uploaded.values()
    assert content_type == "image/jpeg" and b"CameraMaker" not in data
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (20, 40)


# --- API 4：外部サービス・DB ---


def test_unknown_place_is_404_before_gemini(client, analyzer, google, store):
    google.status = 404
    response = analyze(client, {"google_place_id": "missing_place"})
    assert (response.status_code, response.json()["error"]["code"]) == (404, "place_not_found")
    assert analyzer.calls == [] and store.restaurants == {}


def test_google_unavailable_is_503(client, analyzer, google):
    google.status = 500
    assert analyze(client, {"google_place_id": PLACE}).status_code == 503
    assert analyzer.calls == []


def test_place_without_google_key_is_503(app, client, analyzer):
    app.dependency_overrides[get_optional_places_client] = lambda: None
    assert analyze(client, {"google_place_id": PLACE}).status_code == 503
    assert analyze(client).status_code == 201  # 店舗未選択ならキーなしでも解析できる


@pytest.mark.parametrize(
    ("output", "error", "status", "code"),
    [
        ({"dishes": []}, None, 422, "unreadable_menu"),
        ({"dishes": [{"name": "x"}]}, None, 502, "invalid_ai_output"),
        (None, ApiError(504, "timeout"), 504, "timeout"),
        (None, ApiError(503, "service_unavailable"), 503, "service_unavailable"),
    ],
)
def test_ai_failures_save_nothing(client, analyzer, store, output, error, status, code):
    analyzer.output, analyzer.error = output, error
    response = analyze(client, {"google_place_id": PLACE})
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert store.uploaded == {} and store.saved == {} and store.restaurants == {}


def test_db_failure_deletes_image(client, store, caplog):
    store.save_error = make_api_error("22023", "dishes_invalid")
    with caplog.at_level(logging.INFO):
        response = analyze(client)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "validation_error")
    [path] = store.uploaded
    assert store.deleted == [path]
    assert path not in caplog.text


def test_unexpected_db_failure_also_deletes_image(client, store):
    store.save_error = httpx.ConnectError("down")
    assert analyze(client).status_code == 503
    assert store.deleted == list(store.uploaded)


def test_rate_limit_per_minute_and_day(client, analyzer, clock):
    for _ in range(5):
        assert analyze(client).status_code == 201
    response = analyze(client)
    assert (response.status_code, response.json()["error"]["code"]) == (429, "rate_limited")
    assert len(analyzer.calls) == 5  # 上限を超えた分はGeminiを呼ばない
    for minute in range(1, 10):
        clock["now"] += 61
        for _ in range(5):
            assert analyze(client).status_code == 201
    clock["now"] += 61
    assert analyze(client).status_code == 429  # 50回／日
    assert len(analyzer.calls) == 50


# --- API 4：任意のアカウント認証 ---


def test_valid_account_token_sets_owner(client, fake_supabase, store):
    fake_supabase.tables["accounts"] = [{"id": ACCOUNT_ID}]
    response = analyze(client, headers={"Authorization": f"Bearer {account_token()}"})
    assert response.status_code == 201
    assert store.saved[response.json()["menu_id"]]["account_id"] == ACCOUNT_ID


@pytest.mark.parametrize(
    ("header", "code"),
    [
        (lambda: f"Bearer {account_token(exp_delta=-10)}", "account_token_expired"),
        (lambda: f"Bearer {account_token(typ='analysis')}", "unauthorized"),
        (lambda: f"Bearer {account_token(secret='another-secret-0123456789abcdefgh')}", "unauthorized"),
        (lambda: f"Bearer {account_token(sub='22222222-2222-4222-8222-222222222222')}", "unauthorized"),  # 存在しない
        (lambda: f"Bearer {account_token(sub='not-a-uuid')}", "unauthorized"),
        (lambda: "Bearer " + jwt.encode({"sub": ACCOUNT_ID, "typ": "account"}, SECRET, "HS256"), "unauthorized"),
        (lambda: "Bearer " + jwt.encode({"sub": ACCOUNT_ID, "iat": 0, "exp": 2**40, "typ": "account"}, SECRET, "HS512"), "unauthorized"),
        (lambda: "Bearer abc.def", "unauthorized"),
        (lambda: "Bearer " + "A" * 43, "unauthorized"),  # 解析用トークンの形式
        (lambda: "Basic dXNlcjpwYXNz", "unauthorized"),
        (lambda: "Bearer", "unauthorized"),
    ],
)
def test_invalid_account_token_is_401_not_guest(client, fake_supabase, analyzer, store, header, code):
    fake_supabase.tables["accounts"] = [{"id": ACCOUNT_ID}]
    response = analyze(client, headers={"Authorization": header()})
    assert (response.status_code, response.json()["error"]["code"]) == (401, code)
    assert analyzer.calls == [] and store.saved == {}


def test_account_token_without_server_secret_is_401(fake_supabase):
    from app.services.auth import verify_account_token

    fake_supabase.tables["accounts"] = [{"id": ACCOUNT_ID}]
    no_secret = Settings(_env_file=None, allowed_origins=FRONT_ORIGIN)
    with pytest.raises(ApiError) as caught:
        verify_account_token(account_token(), no_secret, fake_supabase)
    assert (caught.value.status_code, caught.value.code) == (401, "unauthorized")


# --- API 5 ---


def analyzed(client, fields=None) -> dict:
    response = analyze(client, fields)
    assert response.status_code == 201
    return response.json()


def get(client, menu_id, token, query=""):
    return client.get(f"/api/v1/menus/{menu_id}{query}", headers={"Authorization": f"Bearer {token}"} if token else {})


def test_get_menu_recomputes_without_gemini(client, analyzer, store):
    created = analyzed(client, {"allergen_ids": ["4"]})
    menu_id, token = created["menu_id"], created["analysis_token"]
    dish_id = store.dishes[menu_id][0].id
    store.menu_answers[menu_id] = (
        [
            MenuAnswer(dish_id, 4, "contains", store.now - timedelta(minutes=5)),
            MenuAnswer(dish_id, 4, "does_not_contain", store.now),  # 最新
        ],
        [MenuAnswer(dish_id, 4, "unknown", store.now)],
    )
    response = get(client, menu_id, token, "?allergen_ids=4,1&dietary_restriction_ids=4")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert "analysis_token" not in body
    assert len(analyzer.calls) == 1  # VLMを再実行しない
    assert [d["dish_id"] for d in body["dishes"]] == [d.id for d in store.dishes[menu_id]]
    shrimp = by_id(body["dishes"][0]["allergens"], "allergen_id")[4]
    assert shrimp["current_answer"]["answer"] == "does_not_contain"
    assert shrimp["current_answer"]["confirmed_at"].endswith("Z")
    assert shrimp["notices"]["ai_staff_mismatch"] is True  # AIの記載「海老天」と食い違い
    assert shrimp["store_history"] is None  # 店舗未選択
    egg = by_id(body["dishes"][0]["allergens"], "allergen_id")[1]
    assert egg["current_answer"] is None  # 未回答は null
    diet = body["dishes"][0]["dietary_restrictions"][0]
    assert diet["current_answer"]["answer"] == "unknown"
    assert diet["notices"]["recheck_current_answer"] is True


def test_get_menu_auth_errors(client, store, fake_supabase):
    first = analyzed(client)
    second = analyzed(client)
    assert get(client, first["menu_id"], None).json()["error"]["code"] == "unauthorized"
    response = get(client, first["menu_id"], second["analysis_token"])  # 他メニューのトークン
    assert (response.status_code, response.json()["error"]["code"]) == (401, "invalid_analysis_token")
    fake_supabase.tables["accounts"] = [{"id": ACCOUNT_ID}]
    assert get(client, first["menu_id"], account_token()).status_code == 401  # アカウント用で代用できない
    assert get(client, str(uuid.uuid4()), first["analysis_token"]).status_code == 404
    assert get(client, "not-a-uuid", first["analysis_token"]).status_code == 422

    menu = store.menus[first["menu_id"]]
    store.menus[first["menu_id"]] = MenuRow(
        menu.id, menu.restaurant_id, menu.google_place_id, menu.analysis_token_hash,
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    response = get(client, first["menu_id"], first["analysis_token"])
    assert (response.status_code, response.json()["error"]["code"]) == (410, "analysis_expired")


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("?allergen_ids=4,4", "invalid_allergen_ids"),
        ("?allergen_ids=30", "invalid_allergen_ids"),
        ("?dietary_restriction_ids=9", "invalid_dietary_restriction_ids"),
        ("?allergen_ids=4&allergen_ids=6", "validation_error"),
        ("?allergen_ids=", "validation_error"),
        ("?allergen_ids=4,,6", "validation_error"),
        ("?allergen_ids=[4]", "validation_error"),
        ("?locale=ja", "validation_error"),
        ("?analysis_token=x", "validation_error"),
    ],
)
def test_get_menu_query_errors(client, query, code):
    created = analyzed(client)
    response = get(client, created["menu_id"], created["analysis_token"], query)
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)


def test_token_is_not_logged(client, caplog):
    with caplog.at_level(logging.DEBUG):
        created = analyzed(client, {"allergen_ids": ["4"]})
        get(client, created["menu_id"], created["analysis_token"], "?allergen_ids=4")
    assert created["analysis_token"] not in caplog.text
    assert hashlib.sha256(created["analysis_token"].encode()).hexdigest() not in caplog.text
