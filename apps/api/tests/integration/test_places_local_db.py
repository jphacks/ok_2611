"""公開料理数（public_menu_count）を、ローカルSupabaseの実際の公開ビューで確認する（Googleはモック）。

試験データを書き込むためローカル専用。終了時に psycopg で削除する。
  LOCAL_SUPABASE_URL=http://127.0.0.1:54321 LOCAL_SUPABASE_SECRET_KEY=<SECRET_KEY> \
  LOCAL_SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m pytest -m local_db
"""

import hashlib
import os
import uuid
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from supabase import create_client

from app.config import Settings
from app.main import create_app
from app.services.places import PlacesClient, get_places_client
from app.services.rate_limit import MemoryRateLimiter, get_rate_limiter

pytestmark = pytest.mark.local_db

URL = os.environ.get("LOCAL_SUPABASE_URL")
KEY = os.environ.get("LOCAL_SUPABASE_SECRET_KEY")
DB_URL = os.environ.get("LOCAL_SUPABASE_DB_URL")
RUN = uuid.uuid4().hex[:10]
TAG = f"api-it-{RUN}"
ARGON = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"
LAT, LNG = 35.6812, 139.7671


def _require_local() -> None:
    if not URL or not KEY or not DB_URL:
        pytest.skip("LOCAL_SUPABASE_URL / LOCAL_SUPABASE_SECRET_KEY / LOCAL_SUPABASE_DB_URL が未設定")
    for value in (URL, DB_URL):
        if urlsplit(value).hostname not in ("127.0.0.1", "localhost"):
            pytest.fail("ローカルSupabase以外には書き込まない")


def _dish(name: str) -> dict:
    return {
        "name": name,
        "name_key": name.replace(" ", "").lower(),
        "translations": {"en": {"name": name, "description": "test"}},
        "price": 1000,
        "currency": "JPY",
        "ai_result": {"ingredients": [], "allergens": [], "dietary_restrictions": []},
    }


@pytest.fixture(scope="module")
def db():
    _require_local()
    client = create_client(URL, KEY)
    yield client
    import psycopg

    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        menus = "select id from public.menus where image_path like %(p)s"
        sessions = f"select id from public.confirmation_sessions where menu_id in ({menus})"
        cur.execute(f"delete from public.confirmation_dietary_answers where session_id in ({sessions})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.confirmation_answers where session_id in ({sessions})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.confirmation_sessions where menu_id in ({menus})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.dishes where menu_id in ({menus})", {"p": f"{TAG}/%"})
        cur.execute("delete from public.menus where image_path like %(p)s", {"p": f"{TAG}/%"})
        cur.execute("delete from public.restaurants where google_place_id like %(p)s", {"p": f"{TAG}%"})
        cur.execute("delete from public.accounts where email like %(p)s", {"p": f"%+{RUN}@example.com"})


def _account(db, consent: bool) -> str:
    return db.table("accounts").insert({
        "email": f"{'yes' if consent else 'no'}+{RUN}@example.com", "nickname": "Test", "password_hash": ARGON,
        "publish_consent": consent, "publish_consent_version": "2026-10-17-v1",
    }).execute().data[0]["id"]


def _menu(
    db, restaurant_id: str | None, account_id: str | None, names: tuple[str, ...] = ("Kake soba", "Tempura soba")
) -> tuple[str, str, list[str]]:
    token = uuid.uuid4().hex
    params = {
        "p_restaurant_id": restaurant_id, "p_image_path": f"{TAG}/{uuid.uuid4().hex}.jpg",
        "p_analysis_token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "p_dishes": [_dish(name) for name in names], "p_ai_model": "test", "p_prompt_version": "v4",
    }
    if account_id:
        params["p_account_id"] = account_id
    menu_id = db.rpc("save_menu_analysis", params).execute().data
    dish_ids = [d["id"] for d in db.table("dishes").select("id").eq("menu_id", menu_id).execute().data]
    return menu_id, params["p_analysis_token_hash"], dish_ids


def _confirm(db, menu_id: str, token_hash: str, dish_ids: list[str], publish: bool) -> None:
    db.rpc("complete_confirmation_session", {
        "p_menu_id": menu_id, "p_analysis_token_hash": token_hash, "p_request_id": str(uuid.uuid4()),
        "p_answers": [{"dish_id": d, "allergen_id": 4, "answer": "not_contains"} for d in dish_ids],
        "p_dietary_answers": [], "p_publish_consent": publish,
    }).execute()


def _client(db, place_ids: list[str]) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"places": [
            {"id": pid, "displayName": {"text": pid}, "location": {"latitude": LAT, "longitude": LNG + i * 0.001},
             "shortFormattedAddress": "test"}
            for i, pid in enumerate(place_ids)
        ]})

    app = create_app(Settings(_env_file=None, supabase_url=URL, supabase_secret_key=KEY))
    app.dependency_overrides[get_places_client] = lambda: PlacesClient("k", transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_rate_limiter] = MemoryRateLimiter
    return TestClient(app)


def test_public_dish_count_uses_only_published_view(db):
    place = f"{TAG}-a"
    empty_place = f"{TAG}-b"
    restaurant = db.table("restaurants").insert({"google_place_id": place}).execute().data[0]["id"]
    db.table("restaurants").insert({"google_place_id": empty_place}).execute()
    yes, no = _account(db, True), _account(db, False)
    client = _client(db, [place, empty_place])

    def counts() -> dict[str, int]:
        body = client.get(f"/api/v1/places/nearby?lat={LAT}&lng={LNG}").json()
        return {p["google_place_id"]: p["public_menu_count"] for p in body["places"]}

    assert counts() == {place: 0, empty_place: 0}

    # 公開：店舗あり・利用者同意あり・店員同意あり。料理2件（name_key 2種類）
    menu, token, dishes = _menu(db, restaurant, yes)
    _confirm(db, menu, token, dishes, publish=True)
    assert counts() == {place: 2, empty_place: 0}

    # 非公開の回答を増やしても件数は増えない
    m, t, d = _menu(db, restaurant, yes)
    _confirm(db, m, t, d, publish=False)  # 店員が不同意
    m, t, d = _menu(db, restaurant, no)
    _confirm(db, m, t, d, publish=True)  # 利用者が不同意
    m, t, d = _menu(db, restaurant, None)
    _confirm(db, m, t, d, publish=True)  # ゲスト（利用者同意false）
    _menu(db, restaurant, yes, ("Curry",))  # 未確認
    m, t, d = _menu(db, None, yes, ("Curry",))
    _confirm(db, m, t, d, publish=True)  # 店舗未選択
    assert counts() == {place: 2, empty_place: 0}

    # 同じメニューに確認を追加しても増えない
    _confirm(db, menu, token, dishes, publish=False)
    _confirm(db, menu, token, dishes, publish=True)
    assert counts() == {place: 2, empty_place: 0}

    # 別の利用者が同じ料理を撮影して公開しても name_key が同じなら増えず、新しい料理だけ増える
    m, t, d = _menu(db, restaurant, yes, ("Kake soba", "Curry"))
    _confirm(db, m, t, d, publish=True)
    assert counts() == {place: 3, empty_place: 0}

    body = client.get(f"/api/v1/places/nearby?lat={LAT}&lng={LNG}").json()
    assert body["places"][0]["has_public_menus"] is True
    assert body["places"][1]["has_public_menus"] is False
