"""不明への復旧を実DB・RPC・非公開Storage・公開ビューまで通す。外部AIはモック。"""

import uuid

import pytest

from app.routers import menus as menus_router
from tests.integration.test_confirmations_local_db import _account, _bearer, _body, _post
from tests.integration.test_menus_local_db import (  # noqa: F401（共有フィクスチャ）
    TAG, _analyze, _dish, _get, analyzer, client, db,
)
from tests.test_openapi_contract import response_schema, validate

pytestmark = pytest.mark.local_db
UNKNOWN = {"status": "unknown", "source": "unavailable", "evidence": "", "weight": None}


def checked(response, path, method="get", status=200):
    assert response.status_code == status, response.text
    body = response.json()
    validate(body, response_schema(path, method, str(status)))
    return body


@pytest.mark.parametrize("version", ["v4", "v5"])
def test_unknown_round_trip_ownership_confirmation_and_publication(db, client, analyzer, monkeypatch, version):
    # v4は旧契約で保存可能だった正常なunknownを用意し、既存データ読取を再現する。
    monkeypatch.setattr(menus_router, "PROMPT_VERSION", version)
    candidate = {"allergen_id": 4, "status": "unknown", "source": "unavailable", "evidence": ""}
    if version == "v5":
        candidate.update(status="explicit_present", source="recipe_inference", evidence="ambiguous")
    raw = _dish("不明を保持する料理", [candidate])
    raw["dietary_restrictions"] = [
        {"dietary_restriction_id": 4, "status": "unknown", "source": "unavailable", "evidence": ""}
    ]
    analyzer.output = {"dishes": [raw]}
    place = f"{TAG}-unknown-{uuid.uuid4().hex[:6]}"
    owner = _bearer(_account(db, True))
    menu = checked(_analyze(client, place, headers=owner, dietary_restriction_ids=["4"]),
                   "/menus/analyze", "post", 201)
    assert menu["prompt_version"] == version
    row = db.table("dishes").select("ai_result,prompt_version").eq("menu_id", menu["menu_id"]).execute().data[0]
    assert row["prompt_version"] == version
    assert row["ai_result"]["allergens"] == [{"allergen_id": 4, **{k: v for k, v in UNKNOWN.items() if k != "weight"}}]
    assert db.table("confirmation_sessions").select("id").eq("menu_id", menu["menu_id"]).execute().data == []
    fetched = checked(_get(client, menu["menu_id"], menu["analysis_token"], "dietary_restriction_ids=4"), "/menus/{menu_id}")
    assert fetched["dishes"] == menu["dishes"] and fetched["prompt_version"] == version
    for item in fetched["dishes"][0]["allergens"] + fetched["dishes"][0]["dietary_restrictions"]:
        assert item["ai"] == UNKNOWN
        assert item["current_answer"] is None and item["store_history"] is None
        assert not any(item["notices"].values())

    own_url = f"/api/v1/me/menus/{menu['menu_id']}?dietary_restriction_ids=4"
    own = checked(client.get(own_url, headers=owner), "/me/menus/{menu_id}")
    assert own["dishes"] == menu["dishes"] and own["prompt_version"] == version
    assert own["confirmations"] == []
    assert client.get(own_url, headers=_bearer(_account(db, True))).status_code == 404
    public_url = f"/api/v1/places/{place}/public-menus?dietary_restriction_ids=4"
    assert checked(client.get(public_url), "/places/{google_place_id}/public-menus")["dishes"] == []

    # 非公開回答を作っても公開されない。公開のunknownは有効な1票だがα・βへは加算しない。
    checked(_post(client, menu, _body(menu, [(0, 4, "contains")], [(0, 4, "not_supported")])),
            "/menus/{menu_id}/confirmations", "post", 201)
    assert checked(client.get(public_url), "/places/{google_place_id}/public-menus")["dishes"] == []
    confirmation = checked(_post(client, menu, _body(menu, [(0, 4, "unknown")], [(0, 4, "unknown")], publish=True)),
                           "/menus/{menu_id}/confirmations", "post", 201)
    assert confirmation["is_public"] is True
    for item in confirmation["results"][0]["allergens"] + confirmation["results"][0]["dietary_restrictions"]:
        assert item["ai"] == UNKNOWN and item["answer"] == "unknown"
    own = checked(client.get(own_url, headers=owner), "/me/menus/{menu_id}")
    assert len(own["confirmations"]) == 2
    assert own["dishes"][0]["allergens"][0]["current_answer"]["answer"] == "unknown"
    assert own["dishes"][0]["allergens"][0]["ai"] == UNKNOWN
    public = checked(client.get(public_url), "/places/{google_place_id}/public-menus")
    [dish] = public["dishes"]
    assert [a["allergen_id"] for a in dish["allergens"]] == [4]
    for item in dish["allergens"] + dish["dietary_restrictions"]:
        assert item["ai"] == UNKNOWN and "current_answer" not in item
        history = item["store_history"]
        assert history["answer_counts"]["unknown"] == 1 and sum(history["answer_counts"].values()) == 1
        assert history["alpha"] == history["beta"] == 1 and history["score"] is None  # 既定の事前値から増えない
    assert analyzer.calls == 1
