"""API 7 をローカルSupabaseの実際の公開ビューで確認する（Gemini・Googleはモック）。"""

import uuid

import pytest

from app.services.publication import count_public_dishes

from tests.integration.test_confirmations_local_db import _account, _bearer, _body, _post
from tests.integration.test_menus_local_db import (  # noqa: F401（フィクスチャ）
    TAG,
    _analyze,
    analyzer,
    client,
    db,
)

pytestmark = pytest.mark.local_db


def _public(client, place, query="?allergen_ids=4&dietary_restriction_ids=4"):
    response = client.get(f"/api/v1/places/{place}/public-menus{query}")
    assert response.status_code == 200, response.text
    return response.json()


def test_only_published_answers_are_aggregated(db, client):
    place = f"{TAG}-pub7-{uuid.uuid4().hex[:6]}"
    yes = _bearer(_account(db, True))
    assert _public(client, place)["dishes"] == []

    # 公開：利用者同意・店員同意・店舗あり
    a = _analyze(client, place, headers=yes).json()
    _post(client, a, _body(a, [(0, 4, "contains")], [(0, 4, "not_supported")], publish=True))
    # 別の利用者の公開回答も集計する
    b = _analyze(client, place, headers=_bearer(_account(db, True))).json()
    _post(client, b, _body(b, [(0, 4, "does_not_contain")], publish=True))

    # 混ざってはいけないもの
    _post(client, a, _body(a, [(0, 4, "shared_utensils")], publish=False))  # 同じメニューの店員不同意の確認
    no = _analyze(client, place, headers=_bearer(_account(db, False))).json()
    _post(client, no, _body(no, [(0, 4, "unknown")], publish=True))  # 利用者不同意
    guest = _analyze(client, place).json()
    _post(client, guest, _body(guest, [(0, 4, "unknown")], publish=True))  # ゲスト
    staff_no = _analyze(client, place, headers=yes).json()
    _post(client, staff_no, _body(staff_no, [(0, 4, "unknown")], publish=False))  # 店員不同意

    body = _public(client, place)
    assert body["staff_answers_verified"] is False and body["match_basis"] == "name_key"
    tempura = next(d for d in body["dishes"] if d["name_key"] == "海老天そば")
    shrimp = tempura["allergens"][0]
    assert shrimp["store_history"]["answer_counts"] == {"contains": 1, "shared_utensils": 0, "does_not_contain": 1, "unknown": 0}
    assert shrimp["store_history"]["score"] == pytest.approx(0.5)
    assert shrimp["notices"]["history_conflict"] is True
    assert shrimp["ai"]["status"] == "explicit_present"  # AIの候補は別に返す
    diet = tempura["dietary_restrictions"][0]
    assert diet["store_history"]["answer_counts"]["not_supported"] == 1
    for leaked in (a["menu_id"], a["dishes"][0]["dish_id"], a["analysis_token"]):
        assert leaked not in str(body)

    # 周辺検索（02）の公開料理数と一致する（2料理：海老天そば・kakesoba）
    assert {d["name_key"] for d in body["dishes"]} == {"海老天そば", "kakesoba"}
    assert count_public_dishes(db, [place]) == {place: len(body["dishes"])}
