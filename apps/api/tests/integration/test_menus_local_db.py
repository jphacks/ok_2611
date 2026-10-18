"""API 4・5 をローカルSupabaseの実際のRPC・Storage・クエリで確認する（Gemini・Googleはモック）。

試験データを書き込むためローカル専用。終了時にStorage APIで画像を、psycopgで行を削除する。
  LOCAL_SUPABASE_URL=http://127.0.0.1:54321 LOCAL_SUPABASE_SECRET_KEY=<SECRET_KEY> \
  LOCAL_SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m pytest -m local_db
"""

import hashlib
import io
import os
import time
import uuid
from urllib.parse import urlsplit

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from supabase import create_client

from app.config import Settings
from app.main import create_app
from app.routers import menus as menus_router
from app.services import menus as menu_store
from app.services.dish_descriptions import get_dish_describer
from app.services.menu_analysis import get_menu_analyzer
from app.services.places import PlacesClient, get_optional_places_client
from app.services.rate_limit import MemoryRateLimiter, get_rate_limiter
from tests.conftest import KeepAnalysisDescriptions

pytestmark = pytest.mark.local_db

URL = os.environ.get("LOCAL_SUPABASE_URL")
KEY = os.environ.get("LOCAL_SUPABASE_SECRET_KEY")
DB_URL = os.environ.get("LOCAL_SUPABASE_DB_URL")
RUN = uuid.uuid4().hex[:10]
TAG = f"api-menus-it-{RUN}"
SECRET = "local-test-jwt-secret-0123456789abcdef"
ARGON = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"


def _require_local() -> None:
    if not URL or not KEY or not DB_URL:
        pytest.skip("LOCAL_SUPABASE_URL / LOCAL_SUPABASE_SECRET_KEY / LOCAL_SUPABASE_DB_URL が未設定")
    for value in (URL, DB_URL):
        if urlsplit(value).hostname not in ("127.0.0.1", "localhost"):
            pytest.fail("ローカルSupabase以外には書き込まない")


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buffer, "JPEG")
    return buffer.getvalue()


def _candidate(allergen_id: int, source: str = "menu_text") -> dict:
    status = {"menu_text": "explicit_present", "recipe_inference": "possible"}[source]
    return {"allergen_id": allergen_id, "status": status, "source": source, "evidence": "海老"}


def _dish(name: str, allergens: list[dict]) -> dict:
    return {
        "name": name,
        "translations": {"en": {"name": name, "description": "AI description"}},
        "price": 1200,
        "currency": "JPY",
        "ingredients": [],
        "allergens": allergens,
        "dietary_restrictions": [
            {"dietary_restriction_id": 4, "status": "possible_conflict", "source": "recipe_inference", "evidence": "mirin"}
        ],
    }


class FakeAnalyzer:
    model = "gemini-test"

    def __init__(self) -> None:
        self.output = {"dishes": [_dish("海老天 そば", [_candidate(4)]), _dish("Kake Soba", [])]}
        self.calls = 0

    def analyze(self, image, allergens, dietary_restrictions):
        self.calls += 1
        return self.output


@pytest.fixture(scope="module")
def db():
    _require_local()
    client = create_client(URL, KEY)
    yield client
    import psycopg

    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute("select image_path from public.menus where image_path like %(p)s", {"p": f"{TAG}/%"})
        paths = [row[0] for row in cur.fetchall()]
        menus = "select id from public.menus where image_path like %(p)s"
        sessions = f"select id from public.confirmation_sessions where menu_id in ({menus})"
        cur.execute(f"delete from public.confirmation_dietary_answers where session_id in ({sessions})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.confirmation_answers where session_id in ({sessions})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.confirmation_sessions where menu_id in ({menus})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.dishes where menu_id in ({menus})", {"p": f"{TAG}/%"})
        cur.execute("delete from public.menus where image_path like %(p)s", {"p": f"{TAG}/%"})
        cur.execute("delete from public.restaurants where google_place_id like %(p)s", {"p": f"{TAG}%"})
        cur.execute("delete from public.accounts where email like %(p)s", {"p": f"%+{RUN}@example.com"})
    leftover = [item["name"] for item in client.storage.from_("menu-images").list(TAG)]
    if paths or leftover:
        client.storage.from_("menu-images").remove(paths + [f"{TAG}/{name}" for name in leftover])


@pytest.fixture
def analyzer() -> FakeAnalyzer:
    return FakeAnalyzer()


@pytest.fixture
def client(db, analyzer, monkeypatch):
    # 後片付けで見つけられるよう、画像のパスに試験のタグを付ける
    monkeypatch.setattr(menu_store, "new_image_path", lambda image: f"{TAG}/{uuid.uuid4()}.{image.extension}")

    def google(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": request.url.path.removeprefix("/v1/places/")})

    settings = Settings(_env_file=None, supabase_url=URL, supabase_secret_key=KEY, auth_jwt_secret=SECRET)
    app = create_app(settings)
    app.dependency_overrides[get_optional_places_client] = lambda: PlacesClient(
        "k", transport=httpx.MockTransport(google)
    )
    app.dependency_overrides[get_menu_analyzer] = lambda: analyzer
    app.dependency_overrides[get_dish_describer] = KeepAnalysisDescriptions
    app.dependency_overrides[get_rate_limiter] = MemoryRateLimiter
    return TestClient(app)


def _analyze(client, place: str | None = None, headers: dict | None = None, **fields):
    data = {"google_place_id": place} if place else {}
    data.update(fields)
    return client.post(
        "/api/v1/menus/analyze", files={"image": ("menu.jpg", _jpeg(), "image/jpeg")}, data=data, headers=headers or {}
    )


def _confirm(db, menu: dict, token: str, answers: list[tuple[int, int, str]], dietary=()) -> None:
    """answers は (料理の位置, allergen_id, DBの値)。"""
    db.rpc("complete_confirmation_session", {
        "p_menu_id": menu["menu_id"],
        "p_analysis_token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "p_request_id": str(uuid.uuid4()),
        "p_answers": [
            {"dish_id": menu["dishes"][pos]["dish_id"], "allergen_id": aid, "answer": value} for pos, aid, value in answers
        ],
        "p_dietary_answers": [
            {"dish_id": menu["dishes"][pos]["dish_id"], "dietary_restriction_id": did, "answer": value}
            for pos, did, value in dietary
        ],
        "p_publish_consent": False,
    }).execute()


def _get(client, menu_id: str, token: str, query: str = "allergen_ids=4,1&dietary_restriction_ids=4"):
    return client.get(f"/api/v1/menus/{menu_id}?{query}", headers={"Authorization": f"Bearer {token}"})


def test_analyze_saves_menu_image_and_restaurant(db, client):
    place = f"{TAG}-store"
    response = _analyze(client, place, allergen_ids=["4", "1"], dietary_restriction_ids=["4"])
    assert response.status_code == 201, response.text
    body = response.json()
    token = body["analysis_token"]
    assert len(token) >= 43 and body["google_place_id"] == place

    row = db.table("menus").select("*").eq("id", body["menu_id"]).execute().data[0]
    assert row["analysis_token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(row)
    assert row["account_id"] is None and row["user_publish_consent"] is False
    restaurant = db.table("restaurants").select("id").eq("google_place_id", place).execute().data
    assert restaurant[0]["id"] == row["restaurant_id"]

    dishes = db.table("dishes").select("*").eq("menu_id", body["menu_id"]).order("position").execute().data
    assert [d["name_key"] for d in dishes] == ["海老天そば", "kakesoba"]
    # 利用者の選択設定（1・4）は保存されない。AIの候補だけ
    assert dishes[0]["ai_result"]["allergens"] == [_candidate(4)]
    assert dishes[1]["ai_result"]["allergens"] == []
    stored = db.storage.from_("menu-images").download(row["image_path"])
    assert stored[:3] == b"\xff\xd8\xff"
    assert "image_path" not in response.text and row["image_path"] not in response.text

    # 同じ店舗の2回目は restaurants を再利用する
    again = _analyze(client, place)
    assert again.status_code == 201
    assert len(db.table("restaurants").select("id").eq("google_place_id", place).execute().data) == 1


def test_get_menu_reflects_new_answers_and_store_history(db, client, analyzer):
    place = f"{TAG}-history"
    first = _analyze(client, place, allergen_ids=["4"]).json()
    second = _analyze(client, place, allergen_ids=["4"]).json()
    other_store = _analyze(client, f"{TAG}-other", allergen_ids=["4"]).json()
    no_store = _analyze(client, None, allergen_ids=["4"]).json()
    assert analyzer.calls == 4

    _confirm(db, first, first["analysis_token"], [(0, 4, "not_contains"), (0, 1, "contains"), (1, 4, "unknown"), (1, 1, "unknown")],
             dietary=[(0, 4, "not_supported"), (1, 4, "supported")])
    _confirm(db, other_store, other_store["analysis_token"], [(0, 4, "contains")])
    _confirm(db, no_store, no_store["analysis_token"], [(0, 4, "contains")])

    response = _get(client, first["menu_id"], first["analysis_token"])
    assert response.status_code == 200, response.text
    assert analyzer.calls == 4  # 再取得でVLMを呼ばない
    assert "analysis_token" not in response.json()
    dish = response.json()["dishes"][0]
    shrimp = next(a for a in dish["allergens"] if a["allergen_id"] == 4)
    assert shrimp["current_answer"]["answer"] == "does_not_contain"  # DBの not_contains をAPIの値へ
    assert shrimp["notices"]["ai_staff_mismatch"] is True
    history = shrimp["store_history"]
    # 別店舗・店舗未選択の contains は数えない
    assert history["answer_counts"] == {"contains": 0, "shared_utensils": 0, "does_not_contain": 1, "unknown": 0}
    assert history["match_basis"] == "name_key"
    assert history["score"] == pytest.approx(1 / 3, abs=1e-3)
    egg = next(a for a in dish["allergens"] if a["allergen_id"] == 1)
    assert egg["ai"] == {"status": "unknown", "source": "unavailable", "evidence": "", "weight": None}
    assert egg["current_answer"]["answer"] == "contains"
    alcohol = dish["dietary_restrictions"][0]
    assert alcohol["current_answer"]["answer"] == "not_supported"
    assert alcohol["store_history"]["answer_counts"]["not_supported"] == 1

    # 同じ店舗・同じ料理名の別メニューでは、今回の回答はなく履歴だけが見える
    other = _get(client, second["menu_id"], second["analysis_token"]).json()["dishes"][0]
    shrimp2 = next(a for a in other["allergens"] if a["allergen_id"] == 4)
    assert shrimp2["current_answer"] is None
    assert shrimp2["store_history"]["answer_counts"]["does_not_contain"] == 1

    # 同じメニューに新しい確認を足すと、最新の回答に置き換わり、履歴はメニューごとに最新の1件だけ
    _confirm(db, first, first["analysis_token"], [(0, 4, "cross_contact")])
    shrimp = next(a for a in _get(client, first["menu_id"], first["analysis_token"]).json()["dishes"][0]["allergens"] if a["allergen_id"] == 4)
    assert shrimp["current_answer"]["answer"] == "shared_utensils"
    assert shrimp["notices"]["ai_staff_mismatch"] is False
    assert shrimp["store_history"]["answer_counts"] == {"contains": 0, "shared_utensils": 1, "does_not_contain": 0, "unknown": 0}
    assert shrimp["store_history"]["score"] is None
    assert shrimp["notices"]["history_shared_utensils"] is True

    # 店舗未選択のメニューは履歴なし
    plain = _get(client, no_store["menu_id"], no_store["analysis_token"]).json()["dishes"][0]["allergens"]
    assert [a["allergen_id"] for a in plain] == [1, 4]  # マスタの表示順（卵1番目・えび6番目）
    assert plain[1]["store_history"] is None and plain[1]["current_answer"]["answer"] == "contains"


def test_tokens_cannot_be_swapped(db, client):
    first = _analyze(client).json()
    second = _analyze(client).json()
    assert _get(client, first["menu_id"], second["analysis_token"]).status_code == 401
    assert _get(client, str(uuid.uuid4()), first["analysis_token"]).status_code == 404

    account = db.table("accounts").insert({
        "email": f"yes+{RUN}@example.com", "nickname": "Test", "password_hash": ARGON,
        "publish_consent": True, "publish_consent_version": "2026-10-17-v1",
    }).execute().data[0]["id"]
    now = int(time.time())
    account_token = jwt.encode({"sub": account, "iat": now, "exp": now + 600, "typ": "account"}, SECRET, "HS256")
    # アカウント用トークンで解析結果は読めない
    assert _get(client, first["menu_id"], account_token).status_code == 401

    owned = _analyze(client, headers={"Authorization": f"Bearer {account_token}"})
    assert owned.status_code == 201
    row = db.table("menus").select("account_id,user_publish_consent").eq("id", owned.json()["menu_id"]).execute().data[0]
    assert row == {"account_id": account, "user_publish_consent": True}

    # 解析用トークンをアカウント用として送ると401（ゲストに降格しない）
    assert _analyze(client, headers={"Authorization": f"Bearer {first['analysis_token']}"}).status_code == 401
    missing = jwt.encode({"sub": str(uuid.uuid4()), "iat": now, "exp": now + 600, "typ": "account"}, SECRET, "HS256")
    assert _analyze(client, headers={"Authorization": f"Bearer {missing}"}).status_code == 401


def test_expired_analysis_is_410(db, client):
    import psycopg

    menu = _analyze(client).json()
    # 期限切れの状態は作成後に更新できないため、期限が過去のメニューを直接作る
    token = uuid.uuid4().hex
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into public.menus (image_path, analysis_token_hash, analysis_expires_at, created_at)"
            " values (%s, %s, now() - interval '1 minute', now() - interval '25 hours') returning id",
            (f"{TAG}/expired.jpg", hashlib.sha256(token.encode()).hexdigest()),
        )
        menu_id = cur.fetchone()[0]
    assert _get(client, str(menu_id), token).status_code == 410
    assert _get(client, menu["menu_id"], menu["analysis_token"]).status_code == 200


def test_db_failure_deletes_uploaded_image(db, client, monkeypatch):
    path = f"{TAG}/{uuid.uuid4()}.jpg"
    monkeypatch.setattr(menu_store, "new_image_path", lambda image: path)
    # RPCが拒否するハッシュを渡して、Storage保存後のDB登録を失敗させる
    monkeypatch.setattr(menus_router, "hash_analysis_token", lambda token: "not-a-sha256")
    response = _analyze(client)
    assert response.status_code == 422
    names = [item["name"] for item in db.storage.from_("menu-images").list(TAG)]
    assert path.split("/", 1)[1] not in names
