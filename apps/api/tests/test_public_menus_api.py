"""API 7 `GET /places/{google_place_id}/public-menus`（公開ビューはモック）。

実際の公開ビューでの公開条件は tests/integration/test_public_menus_local_db.py で確認する。
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.public_menus import PublishedDish, representative_dishes

PLACE = "ChIJ_public_place"
URL = f"/api/v1/places/{PLACE}/public-menus"
NOW = datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def ai_result(*allergens, dietary=()):
    return {"ingredients": [], "allergens": list(allergens), "dietary_restrictions": list(dietary)}


SHRIMP = {"allergen_id": 4, "status": "explicit_present", "source": "menu_text", "evidence": "海老天"}
BUCKWHEAT = {"allergen_id": 6, "status": "possible", "source": "dish_name_inference", "evidence": "Soba."}


def menu_row(menu_id, dish_id, name_key, scanned_at, ai=None, name=None, place=PLACE, price=1200):
    return {
        "google_place_id": place, "menu_id": menu_id, "dish_id": dish_id, "scanned_at": iso(scanned_at),
        "dish_name": name or name_key, "name_key": name_key,
        "translations": {"en": {"name": f"{name or name_key} (en)", "description": "AI description"}},
        "price": price, "currency": "JPY", "ai_result": ai or ai_result(),
    }


def answer_row(menu_id, name_key, item_id, answer, at, session="s1", dish="d1", place=PLACE, key="allergen_id"):
    return {
        "google_place_id": place, "session_id": session, "menu_id": menu_id, "dish_id": dish, "name_key": name_key,
        key: item_id, "answer": answer, "confirmed_at": iso(at),
    }


@pytest.fixture
def views(fake_supabase):
    fake_supabase.tables.update(
        {"published_menus": [], "published_confirmation_answers": [], "published_dietary_answers": []}
    )
    return fake_supabase.tables


def test_representative_dish_and_order():
    t0 = NOW - timedelta(days=2)
    dishes = [
        PublishedDish("m1", "d-a", t0, "そば", "soba", {}, 700, "JPY", {}),
        PublishedDish("m2", "d-b", NOW, "そば（新）", "soba", {}, 800, "JPY", {}),
        PublishedDish("m3", "d-c", NOW, "うどん", "udon", {}, 600, "JPY", {}),
        PublishedDish("m3", "d-d", NOW, "あああ", "aaa", {}, 600, "JPY", {}),
        # 同じ撮影日時なら料理IDの降順
        PublishedDish("m4", "d-z", t0, "天丼", "tendon", {}, 900, "JPY", {}),
        PublishedDish("m5", "d-y", t0, "天丼（別）", "tendon", {}, 950, "JPY", {}),
    ]
    chosen = representative_dishes(dishes)
    assert [d.name_key for d in chosen] == ["aaa", "soba", "udon", "tendon"]  # 撮影日時の降順、同日時はname_key順
    assert next(d for d in chosen if d.name_key == "soba").dish_id == "d-b"
    assert next(d for d in chosen if d.name_key == "tendon").dish_id == "d-z"


def test_empty_place_returns_empty_list(client, views):
    response = client.get(URL)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "google_place_id": PLACE, "match_basis": "name_key", "staff_answers_verified": False, "dishes": []
    }


def test_aggregates_public_answers_of_all_users(client, views, fake_supabase):
    old = NOW - timedelta(days=30)
    views["published_menus"] = [
        menu_row("m1", "d1", "海老天そば", old, ai_result(BUCKWHEAT), name="海老天そば（旧）", price=1100),
        menu_row("m2", "d2", "海老天そば", NOW, ai_result(SHRIMP, BUCKWHEAT)),  # 代表料理
        menu_row("m2", "d3", "かけそば", NOW),
        menu_row("x9", "d9", "海老天そば", NOW, place="other_place"),
    ]
    views["published_confirmation_answers"] = [
        answer_row("m1", "海老天そば", 4, "contains", old),
        answer_row("m2", "海老天そば", 4, "not_contains", NOW, session="s2"),
        answer_row("m3", "海老天そば", 4, "cross_contact", NOW, session="s3"),
        # 同じメニューの古い確認は数えない
        answer_row("m2", "海老天そば", 4, "contains", NOW - timedelta(hours=1), session="s0"),
        answer_row("m4", "海老天そば", 4, "unknown", NOW, session="s4"),
        answer_row("x9", "海老天そば", 4, "contains", NOW, place="other_place"),
        answer_row("m5", "かけそば", 4, "contains", NOW, session="s5"),
    ]
    views["published_dietary_answers"] = [
        answer_row("m1", "海老天そば", 4, "supported", NOW, key="dietary_restriction_id"),
    ]
    response = client.get(URL + "?allergen_ids=4&dietary_restriction_ids=4")
    assert response.status_code == 200, response.text
    body = response.json()
    tempura = next(d for d in body["dishes"] if d["name_key"] == "海老天そば")
    assert (tempura["name"], tempura["price"]) == ("海老天そば", 1200)  # 最新の料理から表示内容
    shrimp = tempura["allergens"][0]
    assert shrimp["ai"] == {"status": "explicit_present", "source": "menu_text", "evidence": "海老天", "weight": None}
    history = shrimp["store_history"]
    assert history["answer_counts"] == {"contains": 1, "shared_utensils": 1, "does_not_contain": 1, "unknown": 1}
    assert (history["alpha"], history["beta"]) == (1.5, 2.0)  # 30日前の「含まれる」は0.5
    assert history["score"] == pytest.approx(1.5 / 3.5, abs=1e-3)
    assert history["has_conflict"] is True
    assert shrimp["notices"] == {"history_conflict": True, "history_shared_utensils": True}
    assert "current_answer" not in shrimp
    diet = tempura["dietary_restrictions"][0]
    assert diet["store_history"]["answer_counts"]["supported"] == 1
    assert diet["notices"] == {"history_conflict": False, "history_cross_contact": False}

    # 返却項目を限定：ID・個別の確認・画像・トークンを返さない
    text = json.dumps(body)
    for leaked in ("m1", "m2", "d1", "d2", "s1", "s2", "menu_id", "dish_id", "session_id", "image", "token", "account"):
        assert leaked not in text, leaked
    # 公開ビューとマスタだけを読む
    assert {q.table for q in fake_supabase.queries} <= {
        "allergens", "dietary_restrictions", "published_menus", "published_confirmation_answers", "published_dietary_answers"
    }


def test_targets_default_to_ai_candidates(client, views):
    views["published_menus"] = [menu_row("m1", "d1", "海老天そば", NOW, ai_result(SHRIMP, BUCKWHEAT))]
    dish = client.get(URL).json()["dishes"][0]
    assert [a["allergen_id"] for a in dish["allergens"]] == [6, 4]  # 表示順（そば→えび）
    assert dish["dietary_restrictions"] == []
    assert all(a["store_history"] is None for a in dish["allergens"])


def test_unknown_only_has_null_score(client, views):
    views["published_menus"] = [menu_row("m1", "d1", "soba", NOW)]
    views["published_confirmation_answers"] = [answer_row("m1", "soba", 1, "unknown", NOW)]
    egg = client.get(URL + "?allergen_ids=1").json()["dishes"][0]["allergens"][0]
    assert egg["store_history"]["answer_counts"]["unknown"] == 1
    assert egg["store_history"]["score"] is None


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("?allergen_ids=4,4", "invalid_allergen_ids"),
        ("?dietary_restriction_ids=5", "invalid_dietary_restriction_ids"),
        ("?allergen_ids=x", "validation_error"),
        ("?locale=ja", "validation_error"),
        ("?menu_id=1", "validation_error"),
    ],
)
def test_query_errors(client, views, query, code):
    response = client.get(URL + query)
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)
