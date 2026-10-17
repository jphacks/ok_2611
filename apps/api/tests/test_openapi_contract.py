"""実装と `contracts/openapi.yaml`（全17操作）の照合。

1. 操作・operationId・パラメーター・本文・ステータス・成功応答の項目（入れ子を含む）が一致すること
   （scripts/compare_openapi.py）。
2. 契約の成功応答の例が、契約のスキーマで有効であること。
3. 実装が返す実際の応答（DB・Gemini・Googleはモック）が、契約のスキーマで有効であること。
OpenAPI 3.1のスキーマはJSON Schema 2020-12として検証する。
"""

from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

yaml = pytest.importorskip("yaml")

from scripts.compare_openapi import CONTRACT, compare  # noqa: E402
from tests.test_menus_api import (  # noqa: E402, F401（フィクスチャ）
    ACCOUNT_ID,
    PLACE,
    account_token,
    analyze,
    analyzer,
    app,
    clock,
    google,
    settings,
    store,
)
from app.services.menus import MenuAnswer, StoreAnswerRow  # noqa: E402

class _JsonLikeLoader(yaml.SafeLoader):
    """日時の文字列を datetime に変換しない（JSONと同じ型で検証する）。"""


_JsonLikeLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
SPEC = yaml.load(Path(CONTRACT).read_text(encoding="utf-8"), Loader=_JsonLikeLoader)


def response_schema(path: str, method: str, status: str) -> dict:
    return SPEC["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]


def validate(instance, schema: dict) -> None:
    Draft202012Validator({"components": SPEC["components"], **schema}).validate(instance)


def test_operations_match_contract():
    assert compare() == []


def success_examples():
    for path, item in SPEC["paths"].items():
        for method, op in item.items():
            for status, response in op.get("responses", {}).items():
                media = (response.get("content") or {}).get("application/json") if "content" in response else None
                if status.startswith("2") and media and "example" in media:
                    yield pytest.param(media["schema"], media["example"], id=f"{method.upper()} {path} {status}")


@pytest.mark.parametrize(("schema", "example"), list(success_examples()))
def test_contract_examples_are_valid(schema, example):
    validate(example, schema)


def test_p0_responses_match_contract_schemas(client, store, fake_supabase):
    fake_supabase.tables["accounts"] = [{"id": ACCOUNT_ID}]
    store.user_publish_consent = True
    store.store_allergen = [
        StoreAnswerRow("m-old", "海老天そば", 4, "contains", store.now - timedelta(days=30)),
        StoreAnswerRow("m-old", "海老天そば", 6, "shared_utensils", store.now),
    ]
    store.store_dietary = [StoreAnswerRow("m-old", "海老天そば", 4, "supported", store.now)]
    created = analyze(
        client,
        {"google_place_id": PLACE, "allergen_ids": ["4", "6", "1"], "dietary_restriction_ids": ["4", "1"]},
        headers={"Authorization": f"Bearer {account_token()}"},
    )
    assert created.status_code == 201
    validate(created.json(), response_schema("/menus/analyze", "post", "201"))
    body = created.json()

    menu_id, token = body["menu_id"], body["analysis_token"]
    dish_id = store.dishes[menu_id][0].id
    store.menu_answers[menu_id] = (
        [MenuAnswer(dish_id, 4, "does_not_contain", store.now), MenuAnswer(dish_id, 6, "unknown", store.now)],
        [MenuAnswer(dish_id, 4, "not_supported", store.now)],
    )
    got = client.get(f"/api/v1/menus/{menu_id}?allergen_ids=4,6,1&dietary_restriction_ids=4,1",
                     headers={"Authorization": f"Bearer {token}"})
    assert got.status_code == 200
    validate(got.json(), response_schema("/menus/{menu_id}", "get", "200"))

    for answer, status in (("does_not_contain", "201"), ("shared_utensils", "201")):
        confirm = client.post(
            f"/api/v1/menus/{menu_id}/confirmations",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "request_id": "66666666-6666-4666-8666-666666666666",
                "answers": [{"dish_id": dish_id, "allergen_id": 4, "answer": answer}],
                "dietary_answers": [{"dish_id": dish_id, "dietary_restriction_id": 4, "answer": "unknown"}],
                "publish_consent": True,
            },
        )
        assert confirm.status_code == 201
        validate(confirm.json(), response_schema("/menus/{menu_id}/confirmations", "post", status))
    store.replayed = True
    replay = client.post(
        f"/api/v1/menus/{menu_id}/confirmations",
        headers={"Authorization": f"Bearer {token}"},
        json={"request_id": "66666666-6666-4666-8666-666666666666", "answers": [{"dish_id": dish_id, "allergen_id": 4, "answer": "contains"}],
              "dietary_answers": [], "publish_consent": False},
    )
    assert replay.status_code == 200
    validate(replay.json(), response_schema("/menus/{menu_id}/confirmations", "post", "200"))


def test_error_responses_match_contract(client):
    response = client.get("/api/v1/menus/00000000-0000-4000-8000-000000000000")
    assert response.status_code == 401
    validate(response.json(), SPEC["components"]["responses"]["unauthorized"]["content"]["application/json"]["schema"])


def test_public_menus_response_matches_contract(client, fake_supabase):
    from tests.test_public_menus_api import NOW, SHRIMP, ai_result, answer_row, menu_row

    place = "ChIJ_public_place"
    fake_supabase.tables.update({
        "published_menus": [menu_row("m1", "d1", "海老天そば", NOW, ai_result(SHRIMP))],
        "published_confirmation_answers": [answer_row("m1", "海老天そば", 4, "cross_contact", NOW)],
        "published_dietary_answers": [answer_row("m1", "海老天そば", 4, "supported", NOW, key="dietary_restriction_id")],
    })
    response = client.get(f"/api/v1/places/{place}/public-menus?allergen_ids=4,1&dietary_restriction_ids=4")
    assert response.status_code == 200
    validate(response.json(), response_schema("/places/{google_place_id}/public-menus", "get", "200"))
