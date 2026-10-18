"""API 7 をローカルSupabaseの実際の公開ビューで確認する（Gemini・Googleはモック）。"""

import uuid

import pytest

from app.services.publication import count_public_dishes

from tests.integration.test_confirmations_local_db import _account, _bearer, _body, _post
from tests.integration.test_menus_local_db import (  # noqa: F401（フィクスチャ）
    TAG,
    _analyze,
    _candidate,
    _dish,
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


def _named(analyzer, *dishes):
    analyzer.output = {"dishes": list(dishes)}


def test_same_dish_from_several_users_is_one_row_with_latest_ai(db, client, analyzer):
    """表記差のある同じ料理を複数の利用者が撮影しても1料理にまとめ、最新の公開料理のAI情報を返す（05）。"""
    place = f"{TAG}-pub7-merge-{uuid.uuid4().hex[:6]}"
    other_place = f"{TAG}-pub7-other-{uuid.uuid4().hex[:6]}"
    first = _dish("海老天 そば", [_candidate(4, "recipe_inference")])
    first["translations"]["en"]["name"] = "Old name"
    _named(analyzer, first, _dish("Kake Soba", []))
    a = _analyze(client, place, headers=_bearer(_account(db, True))).json()
    # 一部の料理・項目だけ回答：メニューの全料理が公開候補になり、未回答の料理は履歴null
    assert _post(client, a, _body(a, [(0, 4, "contains")], publish=True)).status_code == 201

    latest = _dish("海老天　そば", [_candidate(4)])  # 全角空白の表記差
    latest["translations"]["en"]["name"] = "Shrimp tempura soba"
    latest["price"] = None
    _named(analyzer, latest)
    b = _analyze(client, place, headers=_bearer(_account(db, True))).json()
    # 同じメニューへの公開確認を2回送っても、そのメニューの最新1件だけを数える
    assert _post(client, b, _body(b, [(0, 4, "contains")], publish=True)).status_code == 201
    assert _post(client, b, _body(b, [(0, 4, "does_not_contain")], publish=True)).status_code == 201
    before = _public(client, place, "?allergen_ids=4")
    # 公開後、同じメニューへの非公開（店員不同意）の新しい確認は集計・公開状態を変えない
    assert _post(client, b, _body(b, [(0, 4, "shared_utensils")], publish=False)).status_code == 201

    # 別店舗の同名料理（公開）は混ざらない
    _named(analyzer, _dish("海老天そば", [_candidate(4)]))
    c = _analyze(client, other_place, headers=_bearer(_account(db, True))).json()
    assert _post(client, c, _body(c, [(0, 4, "unknown")], publish=True)).status_code == 201

    body = _public(client, place, "?allergen_ids=4")
    assert body == before
    keys = [d["name_key"] for d in body["dishes"]]
    assert sorted(keys) == ["kakesoba", "海老天そば"]
    soba = next(d for d in body["dishes"] if d["name_key"] == "海老天そば")
    assert soba["display_name"] == "Shrimp tempura soba" and soba["price"] is None  # 最新の公開料理を採用
    shrimp = soba["allergens"][0]
    assert shrimp["ai"]["status"] == "explicit_present" and shrimp["ai"]["source"] == "menu_text"
    assert shrimp["ai"]["weight"] is None
    history = shrimp["store_history"]
    assert history["answer_counts"] == {"contains": 1, "shared_utensils": 0, "does_not_contain": 1, "unknown": 0}
    assert history["last_answered_at"]["shared_utensils"] is None
    assert shrimp["notices"] == {"history_conflict": True, "history_shared_utensils": False}
    kake = next(d for d in body["dishes"] if d["name_key"] == "kakesoba")
    assert kake["allergens"][0]["store_history"] is None  # 公開メニュー内の未回答料理

    unknown_only = _public(client, other_place, "?allergen_ids=4")["dishes"][0]["allergens"][0]["store_history"]
    assert unknown_only["score"] is None and unknown_only["answer_counts"]["unknown"] == 1

    text = str(body)
    for menu in (a, b):
        for leaked in (menu["menu_id"], menu["analysis_token"], *(d["dish_id"] for d in menu["dishes"])):
            assert leaked not in text
    assert TAG + "/" not in text  # 画像のパス
    assert "account" not in text and "image" not in text
    assert count_public_dishes(db, [place, other_place]) == {place: 2, other_place: 1}


def test_more_than_twenty_public_dishes_are_returned(db, client, analyzer):
    """1撮影の20料理上限を公開APIに流用せず、複数メニューの料理を欠落なく返す（05・02の21料理以上）。"""
    place = f"{TAG}-pub7-many-{uuid.uuid4().hex[:6]}"
    for start in (0, 11):
        _named(analyzer, *(_dish(f"Dish {i:02d}", []) for i in range(start, start + 11)))
        menu = _analyze(client, place, headers=_bearer(_account(db, True))).json()
        assert _post(client, menu, _body(menu, [(0, 4, "unknown")], publish=True)).status_code == 201
    body = _public(client, place, "?allergen_ids=4")
    assert len(body["dishes"]) == 22
    assert count_public_dishes(db, [place]) == {place: 22}
