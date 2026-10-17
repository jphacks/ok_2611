"""API 8〜12・14〜17 をローカルSupabaseで確認する（Gemini・Googleはモック）。

登録・ログイン・本人設定のRPC・本人履歴のクエリ（所有者・店舗・カーソル）を実際のDBで確かめる。
試験データの後片付けは test_menus_local_db.py の `db` フィクスチャ（メールアドレス・画像パスのタグ）で行う。
"""

import base64
import hashlib
import json
import time
import uuid

import httpx
import jwt
import psycopg
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services import menus as menu_store
from app.services.menu_analysis import get_menu_analyzer
from app.services.places import PlacesClient, get_optional_places_client
from app.services.rate_limit import MemoryRateLimiter, get_rate_limiter
from tests.integration.test_menus_local_db import (  # noqa: F401（フィクスチャ）
    DB_URL,
    KEY,
    RUN,
    SECRET,
    TAG,
    URL,
    _jpeg,
    analyzer,
    db,
)

pytestmark = pytest.mark.local_db
PASSWORD = "correct horse battery"


def contract(instance, path: str, method: str, status: str = "200") -> None:
    """実際の応答が contracts/openapi.yaml のスキーマで有効であること。"""
    from tests.test_openapi_contract import response_schema, validate

    validate(instance, response_schema(path, method, status))


@pytest.fixture
def clock():
    return {"now": time.time()}


@pytest.fixture
def limiter(clock):
    return MemoryRateLimiter(clock=lambda: clock["now"])


@pytest.fixture
def client(db, analyzer, limiter, clock, monkeypatch):
    monkeypatch.setattr(menu_store, "new_image_path", lambda image: f"{TAG}/{uuid.uuid4()}.{image.extension}")
    settings = Settings(_env_file=None, supabase_url=URL, supabase_secret_key=KEY, auth_jwt_secret=SECRET)
    app = create_app(settings)
    app.dependency_overrides[get_optional_places_client] = lambda: PlacesClient(
        "k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": r.url.path.rsplit("/", 1)[1]}))
    )
    app.dependency_overrides[get_menu_analyzer] = lambda: analyzer
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    test_client = TestClient(app)
    test_client.clock = clock  # 解析のレート制限（5回／分）を越えないよう、解析ごとに時計を進める
    return test_client


def email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:6]}+{RUN}@example.com"


def register(client, address=None, consent=True, **extra):
    body = {"email": address or email("acc"), "nickname": " Alex ", "password": PASSWORD, "publish_consent": consent}
    body.update(extra)
    return client.post("/api/v1/auth/register", json=body)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def signed(sub: str, *, typ="account", exp_delta=600, secret=SECRET) -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "iat": now, "exp": now + exp_delta, "typ": typ}, secret, "HS256")


# --- 登録・ログイン ---


@pytest.mark.parametrize("consent", [True, False])
def test_register_stores_hash_and_consent(db, client, consent):
    address = email("reg")
    response = register(client, "  " + address.upper() + " ", consent)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    account = body["account"]
    assert account["email"] == address  # 前後空白を除き小文字に
    assert account["nickname"] == "Alex"
    assert account["publish_consent"] is consent
    assert account["publish_consent_version"] == "2026-10-17-v1"
    assert account["publish_consent_recorded_at"].endswith("Z")
    assert set(account) == {"id", "email", "nickname", "publish_consent", "publish_consent_recorded_at",
                            "publish_consent_version", "created_at"}
    assert body["token_type"] == "bearer"
    claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "iat", "exp", "typ"} and claims["typ"] == "account"
    assert claims["exp"] - claims["iat"] == 24 * 3600
    assert PASSWORD not in response.text
    row = db.table("accounts").select("password_hash").eq("id", account["id"]).execute().data[0]
    assert row["password_hash"].startswith("$argon2id$") and PASSWORD not in row["password_hash"]
    me = client.get("/api/v1/me", headers=auth(body["access_token"]))
    assert me.status_code == 200 and me.json() == account
    contract(body, "/auth/register", "post", "201")
    contract(me.json(), "/me", "get")


@pytest.mark.parametrize(
    "override",
    [
        {"publish_consent": None},
        {"publish_consent": "true"},
        {"email": "not-an-email"},
        {"nickname": "   "},
        {"nickname": "x" * 31},
        {"nickname": "Al\u0007ex"},
        {"password": "short"},
        {"password": "x" * 129},
        {"publish_consent_version": "v0"},
        {"publish_consent_recorded_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_register_validation(client, override):
    response = register(client, **override)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "validation_error")


def test_register_missing_consent_and_password_equal_to_email(client):
    body = {"email": email("miss"), "nickname": "Alex", "password": PASSWORD}
    assert client.post("/api/v1/auth/register", json=body).status_code == 422
    address = email("same")
    assert register(client, address, password=address.upper()).status_code == 422


def test_duplicate_email_is_409_case_insensitive(client):
    address = email("dup")
    assert register(client, address).status_code == 201
    response = register(client, address.upper())
    assert (response.status_code, response.json()["error"]["code"]) == (409, "email_already_registered")


def test_register_rate_limit(client):
    for _ in range(5):
        register(client)
    assert register(client).json()["error"]["code"] == "rate_limited"


def test_login_success_failure_and_rehash(db, client):
    address = email("login")
    account_id = register(client, address).json()["account"]["id"]
    ok = client.post("/api/v1/auth/login", json={"email": f" {address.upper()} ", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["account"]["id"] == account_id
    contract(ok.json(), "/auth/login", "post")
    wrong = client.post("/api/v1/auth/login", json={"email": address, "password": PASSWORD + "x"})
    unknown = client.post("/api/v1/auth/login", json={"email": email("none"), "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"error": {"code": "invalid_credentials", "message": "The email address or password is incorrect."}}

    # 現行より弱いパラメータのハッシュはログイン成功時に再ハッシュする
    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    with psycopg.connect(DB_URL) as conn:
        conn.execute("update public.accounts set password_hash = %s where id = %s", (weak, account_id))
    assert client.post("/api/v1/auth/login", json={"email": address, "password": PASSWORD}).status_code == 200
    stored = db.table("accounts").select("password_hash").eq("id", account_id).execute().data[0]["password_hash"]
    assert stored != weak and not PasswordHasher().check_needs_rehash(stored)


def test_login_failure_rate_limits(client):
    address = email("lock")
    register(client, address)
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": address, "password": "wrong-pass"}).status_code == 401
    # メールアドレス単位5回／15分を超えたら、正しいパスワードでも429
    locked = client.post("/api/v1/auth/login", json={"email": address, "password": PASSWORD})
    assert locked.json()["error"]["code"] == "rate_limited"
    # IP単位10回／分（別のメールアドレスでも数える）
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"email": email("other"), "password": "wrong-pass"})
    other = register(client, email("fresh"))  # 登録は別の上限
    fresh = other.json()["account"]["email"]
    assert client.post("/api/v1/auth/login", json={"email": fresh, "password": PASSWORD}).status_code == 429


def test_account_token_validation(client):
    body = register(client).json()
    account_id = body["account"]["id"]
    for token, code in [
        (signed(account_id, secret="another-secret-0123456789abcdefgh"), "unauthorized"),
        (signed(account_id, exp_delta=-5), "account_token_expired"),
        (signed(account_id, typ="analysis"), "unauthorized"),
        (signed(str(uuid.uuid4())), "unauthorized"),  # 存在しないアカウント
        ("A" * 43, "unauthorized"),  # 解析用トークンの形式
    ]:
        response = client.get("/api/v1/me", headers=auth(token))
        assert (response.status_code, response.json()["error"]["code"]) == (401, code)
    assert client.get("/api/v1/me").status_code == 401


# --- 本人設定 ---


def test_settings_are_per_account_and_not_copied(db, client):
    first = register(client, consent=True).json()
    second = register(client).json()
    token, other = first["access_token"], second["access_token"]
    assert client.get("/api/v1/me/allergens", headers=auth(token)).json() == {"allergen_ids": []}
    put = client.put("/api/v1/me/allergens", headers=auth(token), json={"allergen_ids": [6, 4]})
    assert (put.status_code, put.json()) == (200, {"allergen_ids": [4, 6]})
    contract(put.json(), "/me/allergens", "put")
    contract(client.get("/api/v1/me/allergens", headers=auth(token)).json(), "/me/allergens", "get")
    client.put("/api/v1/me/dietary-restrictions", headers=auth(token), json={"dietary_restriction_ids": [4, 1]})
    diets = client.get("/api/v1/me/dietary-restrictions", headers=auth(token)).json()
    assert diets == {"dietary_restriction_ids": [1, 4]}
    contract(diets, "/me/dietary-restrictions", "get")
    # 他のアカウントには影響しない
    assert client.get("/api/v1/me/allergens", headers=auth(other)).json() == {"allergen_ids": []}
    for body, code in [
        ({"allergen_ids": [4, 4]}, "invalid_allergen_ids"),
        ({"allergen_ids": [30]}, "invalid_allergen_ids"),
        ({"allergen_ids": ["4"]}, "validation_error"),
        ({"allergen_ids": [4], "account_id": second["account"]["id"]}, "validation_error"),
    ]:
        response = client.put("/api/v1/me/allergens", headers=auth(token), json=body)
        assert (response.status_code, response.json()["error"]["code"]) == (422, code)
    bad = client.put("/api/v1/me/dietary-restrictions", headers=auth(token), json={"dietary_restriction_ids": [5]})
    assert bad.json()["error"]["code"] == "invalid_dietary_restriction_ids"
    # 全解除
    assert client.put("/api/v1/me/allergens", headers=auth(token), json={"allergen_ids": []}).json() == {"allergen_ids": []}
    client.put("/api/v1/me/allergens", headers=auth(token), json={"allergen_ids": [4]})

    # ログイン後の解析に所有者と登録時同意が保存され、本人設定はメニューに複製されない
    menu = client.post(
        "/api/v1/menus/analyze", headers=auth(token), files={"image": ("m.jpg", _jpeg(), "image/jpeg")},
        data={"google_place_id": f"{TAG}-me", "allergen_ids": ["1"]},
    ).json()
    row = db.table("menus").select("*").eq("id", menu["menu_id"]).execute().data[0]
    assert (row["account_id"], row["user_publish_consent"]) == (first["account"]["id"], True)
    assert "allergen" not in json.dumps(row)
    dishes = db.table("dishes").select("ai_result").eq("menu_id", menu["menu_id"]).execute().data
    assert all(a["allergen_id"] != 1 for d in dishes for a in d["ai_result"]["allergens"])


# --- 本人履歴 ---


def analyze(client, token=None, place=None):
    client.clock["now"] += 61
    data = {"google_place_id": place} if place else {}
    response = client.post(
        "/api/v1/menus/analyze", headers=auth(token) if token else {}, data=data,
        files={"image": ("m.jpg", _jpeg(), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def confirm(client, menu, publish, answer="contains"):
    body = {
        "request_id": str(uuid.uuid4()),
        "answers": [{"dish_id": menu["dishes"][0]["dish_id"], "allergen_id": 4, "answer": answer}],
        "dietary_answers": [],
        "publish_consent": publish,
    }
    response = client.post(f"/api/v1/menus/{menu['menu_id']}/confirmations", headers=auth(menu["analysis_token"]), json=body)
    assert response.status_code == 201
    return response.json()


def test_history_is_owner_only_with_filters_and_cursor(db, client, limiter):
    owner = register(client, consent=True).json()
    other = register(client, consent=True).json()
    token = owner["access_token"]
    place = f"{TAG}-hist-{uuid.uuid4().hex[:6]}"
    own_public = analyze(client, token, place)
    confirm(client, own_public, publish=True)
    own_private = analyze(client, token, place)
    confirm(client, own_private, publish=False)
    own_unconfirmed = analyze(client, token, place)
    own_no_store = analyze(client, token)
    others = analyze(client, other["access_token"], place)
    guest = analyze(client, None, place)

    listed = client.get("/api/v1/me/menus", headers=auth(token))
    assert listed.status_code == 200 and listed.headers["cache-control"] == "no-store"
    menus = listed.json()["menus"]
    contract(listed.json(), "/me/menus", "get")
    expected = [own_no_store, own_unconfirmed, own_private, own_public]  # 新しい順
    assert [m["menu_id"] for m in menus] == [m["menu_id"] for m in expected]
    by_id = {m["menu_id"]: m for m in menus}
    assert by_id[own_public["menu_id"]]["is_public"] is True
    assert by_id[own_public["menu_id"]]["confirmation_count"] == 1
    assert by_id[own_private["menu_id"]]["is_public"] is False
    assert by_id[own_unconfirmed["menu_id"]]["confirmation_count"] == 0
    assert by_id[own_no_store["menu_id"]]["google_place_id"] is None
    assert by_id[own_public["menu_id"]]["dish_names"] == ["海老天 そば", "Kake Soba"]
    assert by_id[own_public["menu_id"]]["dish_count"] == 2
    text = listed.text
    for leaked in (others["menu_id"], guest["menu_id"], own_public["analysis_token"], owner["account"]["id"]):
        assert leaked not in text

    # 店舗で絞る（店舗未選択を含めない）
    filtered = client.get(f"/api/v1/me/menus?google_place_id={place}", headers=auth(token)).json()["menus"]
    assert [m["menu_id"] for m in filtered] == [m["menu_id"] for m in expected[1:]]

    # ページング
    first = client.get("/api/v1/me/menus?limit=3", headers=auth(token)).json()
    assert len(first["menus"]) == 3 and first["next_cursor"]
    second = client.get(f"/api/v1/me/menus?limit=3&cursor={first['next_cursor']}", headers=auth(token)).json()
    assert [m["menu_id"] for m in first["menus"] + second["menus"]] == [m["menu_id"] for m in expected]
    assert second["next_cursor"] is None

    # 他人のメニューの位置を指すカーソルでも、他人の履歴は混ざらない
    other_row = db.table("menus").select("created_at").eq("id", others["menu_id"]).execute().data[0]
    future = {"t": "2999-01-01T00:00:00+00:00", "id": others["menu_id"]}
    for payload in ({"t": other_row["created_at"], "id": others["menu_id"]}, future):
        cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        got = client.get(f"/api/v1/me/menus?cursor={cursor}", headers=auth(token)).json()["menus"]
        assert {m["menu_id"] for m in got} <= {m["menu_id"] for m in expected}
    for bad in ("not-base64!", base64.urlsafe_b64encode(b'{"t":"x","id":"y"}').decode(), "e30"):
        assert client.get(f"/api/v1/me/menus?cursor={bad}", headers=auth(token)).status_code == 422
    for query in ("?limit=0", "?limit=51", "?account_id=x"):
        assert client.get(f"/api/v1/me/menus{query}", headers=auth(token)).status_code == 422
    # 解析用トークンでは使えない
    assert client.get("/api/v1/me/menus", headers=auth(own_public["analysis_token"])).status_code == 401


def test_menu_detail_owner_only_after_expiry(db, client):
    owner = register(client, consent=True).json()
    other = register(client).json()
    token = owner["access_token"]
    place = f"{TAG}-detail-{uuid.uuid4().hex[:6]}"
    menu = analyze(client, token, place)
    first = confirm(client, menu, publish=False, answer="does_not_contain")
    second = confirm(client, menu, publish=True, answer="contains")
    others = analyze(client, other["access_token"], place)
    confirm(client, others, publish=True, answer="shared_utensils")  # 別の人の確認（公開）
    guest = analyze(client, None, place)

    # 解析用トークンの期限切れ・画像の削除後も読める
    row = db.table("menus").select("image_path").eq("id", menu["menu_id"]).execute().data[0]
    db.storage.from_("menu-images").remove([row["image_path"]])
    with psycopg.connect(DB_URL) as conn:
        conn.execute("alter table public.menus disable trigger trg_menu_immutable")
        try:
            conn.execute(
                "update public.menus set created_at = now() - interval '25 hours',"
                " analysis_expires_at = now() - interval '1 hour' where id = %s",
                (menu["menu_id"],),
            )
        finally:
            conn.execute("alter table public.menus enable trigger trg_menu_immutable")

    response = client.get(f"/api/v1/me/menus/{menu['menu_id']}?allergen_ids=4", headers=auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    contract(body, "/me/menus/{menu_id}", "get")
    assert "analysis_token" not in body and "analysis_expires_at" not in body
    assert (body["user_publish_consent"], body["is_public"]) == (True, True)
    assert [c["session_id"] for c in body["confirmations"]] == [second["session_id"], first["session_id"]]
    assert [c["is_public"] for c in body["confirmations"]] == [True, False]
    assert body["confirmations"][1]["results"][0]["allergens"][0]["answer"] == "does_not_contain"
    shrimp = body["dishes"][0]["allergens"][0]
    assert shrimp["current_answer"]["answer"] == "contains"  # 最新の確認
    # 予測用の集計には他の人の回答も入るが、confirmations には自分のメニューの確認だけ
    assert shrimp["store_history"]["answer_counts"]["shared_utensils"] == 1
    assert len(body["confirmations"]) == 2

    # 期限切れの解析用トークンでは回答を追加できない
    late = client.post(
        f"/api/v1/menus/{menu['menu_id']}/confirmations", headers=auth(menu["analysis_token"]),
        json={"request_id": str(uuid.uuid4()), "answers": [{"dish_id": menu["dishes"][0]["dish_id"], "allergen_id": 4, "answer": "unknown"}],
              "dietary_answers": [], "publish_consent": False},
    )
    assert late.status_code == 410

    for menu_id in (others["menu_id"], guest["menu_id"], str(uuid.uuid4())):
        missing = client.get(f"/api/v1/me/menus/{menu_id}", headers=auth(token))
        assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")
    assert client.get(f"/api/v1/me/menus/{menu['menu_id']}", headers=auth(menu["analysis_token"])).status_code == 401
    assert client.get(f"/api/v1/me/menus/{menu['menu_id']}?allergen_ids=4,4", headers=auth(token)).status_code == 422
