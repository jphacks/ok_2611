"""API 6 `POST /menus/{menu_id}/confirmations`（DB・RPCはモック）。

実際のRPC（再送・409・5回上限・同時送信・公開ビュー）は tests/integration/test_confirmations_local_db.py で確認する。
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.errors import ApiError
from app.schemas.confirmations import AllergenAnswerItem, DietaryAnswerItem
from app.services.confirmations import is_public, validate_answers
from app.services.menus import MenuRow, StoreAnswerRow
from tests.conftest import make_api_error
from tests.test_menus_api import (  # noqa: F401（フィクスチャ）
    ACCOUNT_ID,
    PLACE,
    account_token,
    analyze,
    analyzer,
    app,
    clock,
    describer,
    google,
    settings,
    store,
)

D1, D2, D3 = (str(uuid.UUID(int=i)) for i in (1, 2, 3))
MENU_DISHES = {D1, D2}
ALLERGENS = set(range(1, 30))
DIETARY = {1, 2, 3, 4}


def a(dish, item, answer="contains"):
    return AllergenAnswerItem(dish_id=dish, allergen_id=item, answer=answer)


def d(dish, item, answer="unknown"):
    return DietaryAnswerItem(dish_id=dish, dietary_restriction_id=item, answer=answer)


def check(answers=(), dietary=(), dishes=MENU_DISHES):
    return validate_answers(
        list(answers), list(dietary), allergen_ids=ALLERGENS, dietary_restriction_ids=DIETARY, menu_dish_ids=dishes
    )


def error_code(answers=(), dietary=(), dishes=MENU_DISHES) -> str:
    with pytest.raises(ApiError) as caught:
        check(answers, dietary, dishes)
    assert caught.value.status_code == 422
    return caught.value.code


# --- 入力検証（純粋関数） ---


def test_valid_answers_convert_to_db_values():
    result = check(
        [a(D1, 4, "contains"), a(D1, 6, "does_not_contain"), a(D2, 4, "shared_utensils"), a(D2, 6, "unknown")],
        [d(D1, 4, "not_supported"), d(D2, 4, "cross_contact")],
    )
    assert [x["answer"] for x in result.rpc_answers()] == ["contains", "not_contains", "cross_contact", "unknown"]
    assert set(result.rpc_answers()[0]) == {"dish_id", "allergen_id", "answer"}  # dish_version は送らない
    assert [x["answer"] for x in result.rpc_dietary_answers()] == ["not_supported", "cross_contact"]
    assert result.dish_ids == {D1, D2}


def test_one_side_empty_is_allowed_and_unknown_is_valid():
    assert check([a(D1, 4, "unknown")]).dietary == []
    assert check(dietary=[d(D1, 4, "unknown")]).allergens == []


@pytest.mark.parametrize(
    ("answers", "dietary", "code"),
    [
        ([], [], "answers_invalid"),  # 両方空
        ([AllergenAnswerItem(dish_id=D1, allergen_id=4)], [], "answers_invalid"),  # 未回答
        ([AllergenAnswerItem(allergen_id=4, answer="contains")], [], "answers_invalid"),
        ([AllergenAnswerItem(dish_id=D1, answer="contains")], [], "answers_invalid"),
        ([a(D1, 4, "not_contains")], [], "answers_invalid"),  # 旧値
        ([a(D1, 4, "cross_contact")], [], "answers_invalid"),  # 旧値（食事制限では有効）
        ([a(D1, 4, "safe")], [], "answers_invalid"),
        ([], [d(D1, 4, "contains")], "answers_invalid"),  # アレルゲンの値を食事制限に
        ([a(D1, 4), a(D1, 4, "unknown")], [], "answers_invalid"),  # 重複
        ([a(D1, 30)], [], "answers_invalid"),
        ([], [d(D1, 5)], "answers_invalid"),
        ([a("not-a-uuid", 4)], [], "answers_invalid"),
        ([a(D1.replace("-", ""), 4)], [], "answers_invalid"),
        ([a(D1, 4), a(D2, 6)], [], "answers_invalid"),  # 直積の不足
        ([a(D1, 4)], [d(D2, 4)], "answers_invalid"),  # 料理集合の不一致
        ([a(D3, 4)], [], "dish_not_in_menu"),
        ([a(D1, i, "unknown") for i in range(1, 27)] + [a(D2, i, "unknown") for i in range(1, 27)], [], "answers_invalid"),
    ],
)
def test_invalid_answers(answers, dietary, code):
    assert error_code(answers, dietary) == code


def test_dish_count_limit():
    dishes = [str(uuid.UUID(int=i)) for i in range(1, 12)]
    assert error_code([a(x, 4) for x in dishes], dishes=set(dishes)) == "answers_invalid"
    assert len(check([a(x, 4) for x in dishes[:10]], dishes=set(dishes)).dish_ids) == 10


def test_fifty_answers_is_the_limit():
    dishes = [str(uuid.UUID(int=i)) for i in range(1, 11)]
    fifty = [a(x, i, "unknown") for x in dishes for i in range(1, 6)]
    assert len(check(fifty, dishes=set(dishes)).allergens) == 50
    assert error_code(fifty, [d(dishes[0], 1)], dishes=set(dishes)) == "answers_invalid"


@pytest.mark.parametrize("restaurant", ["r1", None])
@pytest.mark.parametrize("user", [True, False])
@pytest.mark.parametrize("staff", [True, False])
def test_is_public_eight_cases(restaurant, user, staff):
    expected = restaurant is not None and user and staff
    assert is_public(restaurant_id=restaurant, user_publish_consent=user, publish_consent=staff) is expected


# --- API ---


@pytest.fixture
def menu(client):
    response = analyze(client)
    assert response.status_code == 201
    return response.json()


def post(client, menu, body, token=None):
    headers = {"Authorization": f"Bearer {token or menu['analysis_token']}"} if token != "" else {}
    return client.post(f"/api/v1/menus/{menu['menu_id']}/confirmations", json=body, headers=headers)


def body_for(menu, answers=(), dietary=(), publish=False, **extra):
    dishes = menu["dishes"]
    return {
        "request_id": str(uuid.uuid4()),
        "answers": [{"dish_id": dishes[p]["dish_id"], "allergen_id": i, "answer": v} for p, i, v in answers],
        "dietary_answers": [
            {"dish_id": dishes[p]["dish_id"], "dietary_restriction_id": i, "answer": v} for p, i, v in dietary
        ],
        "publish_consent": publish,
        **extra,
    }


def test_confirmation_saves_once_and_returns_results(client, menu, store):
    body = body_for(menu, [(0, 4, "does_not_contain"), (0, 6, "shared_utensils")], [(0, 4, "unknown")], publish=True)
    response = post(client, menu, body)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    [call] = store.confirm_calls
    assert call["menu_id"] == menu["menu_id"]
    assert call["request_id"] == body["request_id"]
    assert call["publish_consent"] is True
    assert [x["answer"] for x in call["answers"]] == ["not_contains", "cross_contact"]
    assert call["dietary_answers"] == [{"dish_id": menu["dishes"][0]["dish_id"], "dietary_restriction_id": 4, "answer": "unknown"}]

    result = response.json()
    assert result["replayed"] is False
    assert result["publish_consent"] is True
    # ゲスト・店舗なし：店員が同意しても公開しない
    assert (result["user_publish_consent"], result["is_public"]) == (False, False)
    assert result["confirmed_at"].endswith("Z")
    [dish] = result["results"]  # 回答した料理だけ
    assert dish["dish_id"] == menu["dishes"][0]["dish_id"]
    buckwheat, shrimp = dish["allergens"]  # マスタの表示順（そば→えび）
    assert shrimp["answer"] == "does_not_contain"
    assert shrimp["answer_label"] == "Not an ingredient (cross-contact not confirmed)"
    assert shrimp["ai"] == {"status": "explicit_present", "source": "menu_text", "evidence": "海老天", "weight": None}
    assert shrimp["notices"]["ai_staff_mismatch"] is True
    assert shrimp["store_history"] is None
    assert buckwheat["answer_label"] == "Shares cooking utensils (ingredients not confirmed)"
    assert buckwheat["notices"]["ai_staff_mismatch"] is False  # 器具共有は不一致にしない
    diet = dish["dietary_restrictions"][0]
    assert (diet["answer"], diet["answer_label"]) == ("unknown", "Unknown")
    assert diet["notices"]["recheck_current_answer"] is True
    for word in ("safe", "Safe", "certified", "Verified"):
        assert word not in response.text


def test_replay_returns_200(client, menu, store):
    store.replayed = True
    response = post(client, menu, body_for(menu, [(0, 4, "contains")]))
    assert (response.status_code, response.json()["replayed"]) == (200, True)


def test_public_when_store_and_both_consents(client, fake_supabase, store):
    fake_supabase.tables["accounts"] = [{"id": ACCOUNT_ID}]
    store.user_publish_consent = True
    store.store_allergen = [
        StoreAnswerRow("m-old", "海老天そば", 4, "contains", store.now - timedelta(days=30)),
    ]
    created = analyze(client, {"google_place_id": PLACE}, headers={"Authorization": f"Bearer {account_token()}"}).json()
    # 保存後の読み取りを再現：今回の回答も履歴に入る
    store.store_allergen.append(StoreAnswerRow(created["menu_id"], "海老天そば", 4, "does_not_contain", store.now))
    result = post(client, created, body_for(created, [(0, 4, "does_not_contain")], publish=True)).json()
    assert (result["user_publish_consent"], result["is_public"]) == (True, True)
    shrimp = result["results"][0]["allergens"][0]
    assert shrimp["store_history"]["answer_counts"] == {"contains": 1, "shared_utensils": 0, "does_not_contain": 1, "unknown": 0}
    assert shrimp["notices"]["history_conflict"] is True
    not_public = post(client, created, body_for(created, [(0, 4, "contains")], publish=False)).json()
    assert (not_public["user_publish_consent"], not_public["is_public"]) == (True, False)


@pytest.mark.parametrize(
    "body_change",
    [
        lambda b: b.pop("request_id"),
        lambda b: b.update(request_id="not-a-uuid"),
        lambda b: b.pop("answers"),
        lambda b: b.update(answers=None),
        lambda b: b.pop("dietary_answers"),
        lambda b: b.pop("publish_consent"),
        lambda b: b.update(publish_consent=None),
        lambda b: b.update(publish_consent="true"),
        lambda b: b.update(user_publish_consent=True),  # 利用者同意はクライアントから更新させない
        lambda b: b.update(account_id=ACCOUNT_ID),
        lambda b: b.update(locale="ja"),
        lambda b: b["answers"][0].update(dish_version=1),
        lambda b: b["answers"][0].update(allergen_id="4"),
    ],
)
def test_malformed_body_is_validation_error(client, menu, store, body_change):
    body = body_for(menu, [(0, 4, "contains")])
    body_change(body)
    response = post(client, menu, body)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "validation_error")
    assert store.confirm_calls == []


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ([{"dish_id": None, "allergen_id": 4, "answer": "contains"}], "answers_invalid"),
        ([{"allergen_id": 4, "answer": "not_contains"}], "answers_invalid"),
        ([{"allergen_id": 4, "answer": "cross_contact"}], "answers_invalid"),
        ([{"allergen_id": 4, "answer": None}], "answers_invalid"),
        ([{"allergen_id": 4}], "answers_invalid"),
    ],
)
def test_answer_errors_do_not_call_rpc(client, menu, store, answers, code):
    body = {
        "request_id": str(uuid.uuid4()),
        "answers": [{"dish_id": menu["dishes"][0]["dish_id"], **x} for x in answers],
        "dietary_answers": [],
        "publish_consent": False,
    }
    response = post(client, menu, body)
    assert (response.status_code, response.json()["error"]["code"]) == (422, code)
    assert store.confirm_calls == []


def test_dish_from_other_menu(client, menu, store):
    other = analyze(client).json()
    body = body_for(menu, [(0, 4, "contains")])
    body["answers"][0]["dish_id"] = other["dishes"][0]["dish_id"]
    response = post(client, menu, body)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "dish_not_in_menu")
    assert store.confirm_calls == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (make_api_error("40001", "request_id_conflict"), 409, "request_id_conflict"),
        (make_api_error("22023", "confirmation_limit_reached"), 422, "confirmation_limit_reached"),
        (make_api_error("P0003", "analysis_expired"), 410, "analysis_expired"),
        (make_api_error("28000", "invalid_analysis_token"), 401, "invalid_analysis_token"),
        (make_api_error("22023", "answers_invalid"), 422, "answers_invalid"),
    ],
)
def test_rpc_errors(client, menu, store, error, status, code):
    store.confirm_error = error
    response = post(client, menu, body_for(menu, [(0, 4, "contains")]))
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)


def test_auth_is_checked_before_body(client, menu, store, fake_supabase):
    other = analyze(client).json()
    bad_body = {"unexpected": True}
    assert post(client, menu, bad_body, token="").json()["error"]["code"] == "unauthorized"
    assert post(client, menu, bad_body, token=other["analysis_token"]).json()["error"]["code"] == "invalid_analysis_token"
    fake_supabase.tables["accounts"] = [{"id": ACCOUNT_ID}]
    assert post(client, menu, body_for(menu, [(0, 4, "contains")]), token=account_token()).status_code == 401
    missing = {"menu_id": str(uuid.uuid4()), "analysis_token": menu["analysis_token"]}
    assert post(client, missing, bad_body).status_code == 404

    row = store.menus[menu["menu_id"]]
    store.menus[menu["menu_id"]] = MenuRow(
        row.id, row.restaurant_id, row.google_place_id, row.analysis_token_hash,
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert post(client, menu, bad_body).json()["error"]["code"] == "analysis_expired"
    assert store.confirm_calls == []


def test_token_and_answers_are_not_logged(client, menu, caplog):
    with caplog.at_level(logging.DEBUG):
        post(client, menu, body_for(menu, [(0, 4, "does_not_contain")]))
    assert menu["analysis_token"] not in caplog.text
    assert "does_not_contain" not in caplog.text
