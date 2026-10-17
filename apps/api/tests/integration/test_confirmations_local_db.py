"""API 6 をローカルSupabaseの実際の `complete_confirmation_session`・公開ビューで確認する（Gemini・Googleはモック）。

試験データの作成・後片付けは test_menus_local_db.py のフィクスチャを使う（同じタグで削除する）。
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import jwt
import pytest

from tests.integration.test_menus_local_db import (  # noqa: F401（フィクスチャ）
    ARGON,
    RUN,
    SECRET,
    TAG,
    _analyze,
    _dish,
    _get,
    analyzer,
    client,
    db,
)

pytestmark = pytest.mark.local_db


def _account(db, consent: bool) -> str:
    return db.table("accounts").insert({
        "email": f"conf-{'yes' if consent else 'no'}-{uuid.uuid4().hex[:6]}+{RUN}@example.com",
        "nickname": "Test", "password_hash": ARGON,
        "publish_consent": consent, "publish_consent_version": "2026-10-17-v1",
    }).execute().data[0]["id"]


def _bearer(account_id: str) -> dict:
    now = int(time.time())
    token = jwt.encode({"sub": account_id, "iat": now, "exp": now + 600, "typ": "account"}, SECRET, "HS256")
    return {"Authorization": f"Bearer {token}"}


def _post(client, menu: dict, body: dict, token: str | None = None):
    return client.post(
        f"/api/v1/menus/{menu['menu_id']}/confirmations",
        json=body,
        headers={"Authorization": f"Bearer {token or menu['analysis_token']}"},
    )


def _body(menu: dict, allergens=(), dietary=(), publish=False, request_id=None) -> dict:
    """allergens・dietary は (料理の位置, 項目ID, APIの値)。"""
    dishes = menu["dishes"]
    return {
        "request_id": request_id or str(uuid.uuid4()),
        "answers": [{"dish_id": dishes[p]["dish_id"], "allergen_id": i, "answer": a} for p, i, a in allergens],
        "dietary_answers": [
            {"dish_id": dishes[p]["dish_id"], "dietary_restriction_id": i, "answer": a} for p, i, a in dietary
        ],
        "publish_consent": publish,
    }


def _sessions(db, menu_id: str) -> list[dict]:
    return db.table("confirmation_sessions").select("id,publish_consent").eq("menu_id", menu_id).execute().data


def _db_answers(db, session_id: str) -> tuple[list[str], list[str]]:
    allergens = db.table("confirmation_answers").select("answer").eq("session_id", session_id).execute().data
    dietary = db.table("confirmation_dietary_answers").select("answer").eq("session_id", session_id).execute().data
    return sorted(r["answer"] for r in allergens), sorted(r["answer"] for r in dietary)


def test_allergen_dietary_both_and_values_round_trip(db, client):
    place = f"{TAG}-conf-store"
    menu = _analyze(client, place).json()

    # アレルゲンのみ。APIの値 → DBの値（not_contains・cross_contact）
    response = _post(client, menu, _body(menu, [(0, 4, "does_not_contain"), (0, 6, "shared_utensils"),
                                               (1, 4, "unknown"), (1, 6, "contains")]))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["replayed"] is False and body["is_public"] is False
    assert _db_answers(db, body["session_id"]) == (["contains", "cross_contact", "not_contains", "unknown"], [])
    shrimp = body["results"][0]["allergens"][1]
    assert shrimp["allergen_id"] == 4 and shrimp["answer"] == "does_not_contain"
    assert shrimp["answer_label"] == "Not an ingredient (cross-contact not confirmed)"
    assert shrimp["ai"]["status"] == "explicit_present"  # AIの候補は別に返す
    assert shrimp["notices"]["ai_staff_mismatch"] is True
    buckwheat = body["results"][0]["allergens"][0]
    assert buckwheat["answer_label"] == "Shares cooking utensils (ingredients not confirmed)"

    # 03の再取得で今回の回答として表示され、値はAPIの値に戻る
    got = _get(client, menu["menu_id"], menu["analysis_token"], "allergen_ids=4,6").json()["dishes"][0]
    assert {a["allergen_id"]: a["current_answer"]["answer"] for a in got["allergens"]} == {6: "shared_utensils", 4: "does_not_contain"}

    # 食事制限のみ（unknown は有効な回答）
    response = _post(client, menu, _body(menu, dietary=[(0, 4, "unknown"), (1, 4, "not_supported")]))
    assert response.status_code == 201
    assert _db_answers(db, response.json()["session_id"]) == ([], ["not_supported", "unknown"])
    assert response.json()["results"][0]["dietary_restrictions"][0]["answer_label"] == "Unknown"

    # 両方
    response = _post(client, menu, _body(menu, [(0, 4, "contains")], [(0, 1, "supported")], publish=True))
    assert response.status_code == 201
    assert _db_answers(db, response.json()["session_id"]) == (["contains"], ["supported"])
    assert len(_sessions(db, menu["menu_id"])) == 3


def test_invalid_answers_are_not_saved(db, client, analyzer):
    menu = _analyze(client).json()
    other = _analyze(client).json()
    d0, d1 = menu["dishes"][0]["dish_id"], menu["dishes"][1]["dish_id"]
    cases = [
        ({"answers": [{"dish_id": d0, "allergen_id": 4}]}, "answers_invalid"),  # 未回答（欠落）
        ({"answers": [{"dish_id": d0, "allergen_id": 4, "answer": None}]}, "answers_invalid"),  # null
        ({"answers": [{"dish_id": d0, "allergen_id": 4, "answer": "not_contains"}]}, "answers_invalid"),  # 旧値
        ({"answers": [{"dish_id": d0, "allergen_id": 4, "answer": "cross_contact"}]}, "answers_invalid"),  # 旧値
        ({"answers": [], "dietary_answers": []}, "answers_invalid"),  # 両方空
        ({"answers": [{"dish_id": d0, "allergen_id": 4, "answer": "contains"},
                      {"dish_id": d1, "allergen_id": 6, "answer": "contains"}]}, "answers_invalid"),  # 直積の不足
        ({"answers": [{"dish_id": d0, "allergen_id": 4, "answer": "contains"}],
          "dietary_answers": [{"dish_id": d1, "dietary_restriction_id": 4, "answer": "unknown"}]}, "answers_invalid"),
        ({"answers": [{"dish_id": d0, "allergen_id": 30, "answer": "contains"}]}, "answers_invalid"),
        ({"answers": [{"dish_id": other["dishes"][0]["dish_id"], "allergen_id": 4, "answer": "contains"}]}, "dish_not_in_menu"),
        ({"answers": [{"dish_id": d0, "allergen_id": i, "answer": "unknown"} for i in range(1, 30)]
                     + [{"dish_id": d1, "allergen_id": i, "answer": "unknown"} for i in range(1, 30)]}, "answers_invalid"),  # 58件
    ]
    for override, code in cases:
        body = {"request_id": str(uuid.uuid4()), "answers": [], "dietary_answers": [], "publish_consent": True, **override}
        response = _post(client, menu, body)
        assert (response.status_code, response.json()["error"]["code"]) == (422, code), override
    assert _post(client, menu, {**_body(menu, [(0, 4, "contains")]), "user_publish_consent": True}).status_code == 422
    assert _sessions(db, menu["menu_id"]) == []  # 部分保存なし

    # 11料理の和集合
    analyzer.output = {"dishes": [_dish(f"料理{i}", []) for i in range(11)]}
    big = _analyze(client).json()
    response = _post(client, big, _body(big, [(i, 4, "unknown") for i in range(11)]))
    assert (response.status_code, response.json()["error"]["code"]) == (422, "answers_invalid")
    assert _sessions(db, big["menu_id"]) == []


def test_replay_conflict_limit_and_concurrency(db, client):
    menu = _analyze(client).json()
    request_id = str(uuid.uuid4())
    body = _body(menu, [(0, 4, "contains"), (0, 6, "unknown"), (1, 4, "unknown"), (1, 6, "unknown")],
                 [(0, 4, "unknown"), (1, 4, "unknown")], request_id=request_id)
    first = _post(client, menu, body)
    assert first.status_code == 201
    # 並び順だけ変えた再送は200で同じ確認
    reordered = {**body, "answers": list(reversed(body["answers"])), "dietary_answers": list(reversed(body["dietary_answers"]))}
    again = _post(client, menu, reordered)
    assert (again.status_code, again.json()["replayed"]) == (200, True)
    assert again.json()["session_id"] == first.json()["session_id"]
    assert again.json()["confirmed_at"] == first.json()["confirmed_at"]
    # 同じIDで回答・店員同意が違えば409
    changed = {**body, "answers": [dict(body["answers"][0], answer="does_not_contain")] + body["answers"][1:]}
    assert _post(client, menu, changed).json()["error"]["code"] == "request_id_conflict"
    assert _post(client, menu, {**body, "publish_consent": True}).status_code == 409

    # 同時送信でも1件
    concurrent = _body(menu, [(0, 4, "contains")])
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = sorted(r.status_code for r in pool.map(lambda _: _post(client, menu, concurrent), range(4)))
    assert statuses == [200, 200, 200, 201]
    assert len(_sessions(db, menu["menu_id"])) == 2

    for _ in range(3):
        assert _post(client, menu, _body(menu, [(0, 4, "unknown")])).status_code == 201
    sixth = _post(client, menu, _body(menu, [(0, 4, "unknown")]))
    assert (sixth.status_code, sixth.json()["error"]["code"]) == (422, "confirmation_limit_reached")
    assert _post(client, menu, body).status_code == 200  # 上限到達後も同一内容の再送は成功
    assert len(_sessions(db, menu["menu_id"])) == 5


def test_auth_for_confirmation(db, client):
    menu = _analyze(client).json()
    other = _analyze(client).json()
    body = _body(menu, [(0, 4, "contains")])
    assert _post(client, menu, body, token=other["analysis_token"]).json()["error"]["code"] == "invalid_analysis_token"
    account = _account(db, True)
    account_jwt = _bearer(account)["Authorization"].split(" ", 1)[1]
    assert _post(client, menu, body, token=account_jwt).status_code == 401  # アカウント用では保存できない
    no_token = client.post(f"/api/v1/menus/{menu['menu_id']}/confirmations", json=body)
    assert no_token.status_code == 401
    assert _sessions(db, menu["menu_id"]) == []


@pytest.mark.parametrize("with_store", [True, False])
@pytest.mark.parametrize("user_consent", [True, False])
@pytest.mark.parametrize("staff_consent", [True, False])
def test_publication_eight_cases(db, client, with_store, user_consent, staff_consent):
    place = f"{TAG}-pub-{uuid.uuid4().hex[:6]}" if with_store else None
    menu = _analyze(client, place, headers=_bearer(_account(db, user_consent))).json()
    response = _post(client, menu, _body(menu, [(0, 4, "contains")], publish=staff_consent))
    assert response.status_code == 201
    body = response.json()
    expected = with_store and user_consent and staff_consent
    assert (body["publish_consent"], body["user_publish_consent"], body["is_public"]) == (staff_consent, user_consent, expected)
    published = db.table("published_confirmation_answers").select("session_id").eq("session_id", body["session_id"]).execute().data
    assert bool(published) is expected


def test_guest_and_other_session_consent_do_not_publish(db, client):
    place = f"{TAG}-guest"
    guest = _analyze(client, place).json()
    body = _post(client, guest, _body(guest, [(0, 4, "contains")], publish=True)).json()
    assert (body["user_publish_consent"], body["is_public"]) == (False, False)

    owned = _analyze(client, place, headers=_bearer(_account(db, True))).json()
    public = _post(client, owned, _body(owned, [(0, 4, "contains")], publish=True)).json()
    private = _post(client, owned, _body(owned, [(0, 4, "does_not_contain")], publish=False)).json()
    assert public["is_public"] is True and private["is_public"] is False
    published = db.table("published_confirmation_answers").select("session_id").eq("session_id", private["session_id"]).execute().data
    assert published == []


def test_saved_answers_feed_next_analysis_beta_counts(db, client):
    place = f"{TAG}-beta"
    for allergen_answer, dietary_answer in [("contains", "not_supported"), ("does_not_contain", "supported"),
                                            ("does_not_contain", "supported"), ("shared_utensils", "cross_contact"),
                                            ("unknown", "unknown")]:
        menu = _analyze(client, place).json()
        assert _post(client, menu, _body(menu, [(0, 4, allergen_answer)], [(0, 4, dietary_answer)])).status_code == 201

    nxt = _analyze(client, place, allergen_ids=["4"], dietary_restriction_ids=["4"]).json()["dishes"][0]
    shrimp = nxt["allergens"][0]["store_history"]
    assert shrimp["answer_counts"] == {"contains": 1, "shared_utensils": 1, "does_not_contain": 2, "unknown": 1}
    assert (shrimp["alpha"], shrimp["beta"], shrimp["score"]) == (2.0, 3.0, 0.4)
    diet = nxt["dietary_restrictions"][0]["store_history"]
    assert diet["answer_counts"] == {"not_supported": 1, "cross_contact": 1, "supported": 2, "unknown": 1}
    assert (diet["alpha"], diet["beta"], diet["score"]) == (2.0, 3.0, 0.4)
    assert nxt["allergens"][0]["current_answer"] is None  # 新しい解析には今回の回答はない
