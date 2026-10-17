"""P0の一巡（05）：解析 → 再取得 → 店員確認 → 再取得 → 同じ店舗・料理の次の解析。

ローカルSupabaseの実際のRPC・Storageを使い、Gemini・Googleはモック。画像の手動削除の手順もここで確認する。
試験データの作成・後片付けは test_menus_local_db.py のフィクスチャを使う。
"""

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from scripts.delete_expired_images import run as delete_expired_images
from tests.integration.test_menus_local_db import (  # noqa: F401（フィクスチャ）
    DB_URL,
    TAG,
    _analyze,
    _get,
    _jpeg,
    analyzer,
    client,
    db,
)

pytestmark = pytest.mark.local_db


def _confirm(client, menu, allergens=(), dietary=(), publish=False, request_id=None):
    dishes = menu["dishes"]
    body = {
        "request_id": request_id or str(uuid.uuid4()),
        "answers": [{"dish_id": dishes[p]["dish_id"], "allergen_id": i, "answer": a} for p, i, a in allergens],
        "dietary_answers": [
            {"dish_id": dishes[p]["dish_id"], "dietary_restriction_id": i, "answer": a} for p, i, a in dietary
        ],
        "publish_consent": publish,
    }
    return client.post(
        f"/api/v1/menus/{menu['menu_id']}/confirmations",
        json=body,
        headers={"Authorization": f"Bearer {menu['analysis_token']}"},
    ), body


def _item(dish: dict, key: str, item_id: int) -> dict:
    id_key = "allergen_id" if key == "allergens" else "dietary_restriction_id"
    return next(x for x in dish[key] if x[id_key] == item_id)


def test_p0_round_trip_with_store(db, client, analyzer):
    place = f"{TAG}-flow"
    # ⑩ 解析（アレルゲン・食事制限の両方を対象に）
    first = _analyze(client, place, allergen_ids=["4", "6"], dietary_restriction_ids=["4"])
    assert first.status_code == 201
    menu = first.json()
    assert _item(menu["dishes"][0], "allergens", 4)["store_history"] is None

    # ⑪ 再取得（VLMは再実行しない）
    assert _get(client, menu["menu_id"], menu["analysis_token"], "allergen_ids=4,6").status_code == 200
    assert analyzer.calls == 1

    # ⑬⑭ 店員確認（4択すべて・食事制限の対応できない／対応している）
    saved, body = _confirm(
        client, menu,
        allergens=[(0, 4, "contains"), (0, 6, "shared_utensils"), (1, 4, "does_not_contain"), (1, 6, "unknown")],
        dietary=[(0, 4, "not_supported"), (1, 4, "supported")],
        publish=True,
    )
    assert saved.status_code == 201
    # 結果不明後の再送は同じ確認
    replay, _ = _confirm(client, menu, request_id=body["request_id"],
                         allergens=[(0, 4, "contains"), (0, 6, "shared_utensils"), (1, 4, "does_not_contain"), (1, 6, "unknown")],
                         dietary=[(0, 4, "not_supported"), (1, 4, "supported")], publish=True)
    assert (replay.status_code, replay.json()["session_id"]) == (200, saved.json()["session_id"])
    assert saved.json()["is_public"] is False  # ゲストは店員が同意しても非公開

    # ⑪′ 再取得で今回の回答
    again = _get(client, menu["menu_id"], menu["analysis_token"], "allergen_ids=4,6&dietary_restriction_ids=4").json()
    assert _item(again["dishes"][0], "allergens", 4)["current_answer"]["answer"] == "contains"
    assert _item(again["dishes"][0], "allergens", 6)["current_answer"]["answer"] == "shared_utensils"
    assert _item(again["dishes"][1], "allergens", 4)["current_answer"]["answer"] == "does_not_contain"
    assert _item(again["dishes"][1], "dietary_restrictions", 4)["current_answer"]["answer"] == "supported"

    # 同じ店舗・同じ料理の次の解析
    nxt = _analyze(client, place, allergen_ids=["4", "6"], dietary_restriction_ids=["4"]).json()
    tempura, kake = nxt["dishes"]
    shrimp = _item(tempura, "allergens", 4)["store_history"]
    assert (shrimp["alpha"], shrimp["beta"], shrimp["score"]) == (2.0, 1.0, 0.667)  # 含まれる → α
    buckwheat = _item(tempura, "allergens", 6)["store_history"]
    assert buckwheat["answer_counts"]["shared_utensils"] == 1 and buckwheat["score"] is None  # 器具共有は件数だけ
    assert _item(tempura, "allergens", 6)["notices"]["history_shared_utensils"] is True
    kake_shrimp = _item(kake, "allergens", 4)["store_history"]
    assert (kake_shrimp["alpha"], kake_shrimp["beta"]) == (1.0, 2.0)  # 含まれない → β
    kake_buckwheat = _item(kake, "allergens", 6)["store_history"]
    assert kake_buckwheat["answer_counts"]["unknown"] == 1 and kake_buckwheat["score"] is None  # 不明は件数だけ
    assert _item(tempura, "dietary_restrictions", 4)["store_history"]["alpha"] == 2.0  # not_supported → α
    assert _item(kake, "dietary_restrictions", 4)["store_history"]["beta"] == 2.0  # supported → β
    assert _item(tempura, "allergens", 4)["current_answer"] is None


def test_p0_round_trip_without_store(db, client):
    menu = _analyze(client, None, dietary_restriction_ids=["4"]).json()  # アレルゲンは対象省略（AIの候補）
    assert [a["allergen_id"] for a in menu["dishes"][0]["allergens"]] == [4]
    saved, _ = _confirm(client, menu, dietary=[(0, 4, "unknown")], publish=True)
    assert saved.status_code == 201 and saved.json()["is_public"] is False
    nxt = _analyze(client, None, dietary_restriction_ids=["4"]).json()
    assert nxt["dishes"][0]["dietary_restrictions"][0]["store_history"] is None  # 店舗未選択の回答は使わない


def test_expired_analysis_rejects_read_and_confirmation(db, client):
    import psycopg

    token = uuid.uuid4().hex
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into public.menus (image_path, analysis_token_hash, analysis_expires_at, created_at)"
            " values (%s, %s, now() - interval '1 minute', now() - interval '25 hours') returning id",
            (f"{TAG}/flow-expired.jpg", hashlib.sha256(token.encode()).hexdigest()),
        )
        menu_id = str(cur.fetchone()[0])
    menu = {"menu_id": menu_id, "analysis_token": token, "dishes": [{"dish_id": str(uuid.uuid4())}]}
    assert _get(client, menu_id, token).json()["error"]["code"] == "analysis_expired"
    response, _ = _confirm(client, menu, allergens=[(0, 4, "contains")])
    assert response.json()["error"]["code"] == "analysis_expired"


def test_manual_image_cleanup_keeps_rows(db, client):
    import psycopg

    prefix = f"{TAG}/cleanup-{uuid.uuid4().hex[:6]}/"
    old_path = f"{prefix}old.jpg"
    db.storage.from_("menu-images").upload(old_path, _jpeg(), {"content-type": "image/jpeg"})
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into public.menus (image_path, analysis_token_hash, analysis_expires_at, created_at)"
            " values (%s, %s, now() - interval '1 hour', now() - interval '25 hours') returning id",
            (old_path, hashlib.sha256(uuid.uuid4().bytes).hexdigest()),
        )
        old_menu = str(cur.fetchone()[0])
    fresh_path = f"{prefix}fresh.jpg"
    db.storage.from_("menu-images").upload(fresh_path, _jpeg(), {"content-type": "image/jpeg"})
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into public.menus (image_path, analysis_token_hash) values (%s, %s)",
            (fresh_path, hashlib.sha256(uuid.uuid4().bytes).hexdigest()),
        )

    now = datetime.now(timezone.utc)
    dry = delete_expired_images(db, apply=False, now=now, path_prefix=prefix)
    assert dry == {"expired_menus": 1, "images_remaining": 1, "deleted": 0}
    names = {item["name"] for item in db.storage.from_("menu-images").list(prefix.rstrip("/"))}
    assert names == {"old.jpg", "fresh.jpg"}  # 表示だけでは消さない

    applied = delete_expired_images(db, apply=True, now=now, path_prefix=prefix)
    assert applied == {"expired_menus": 1, "images_remaining": 1, "deleted": 1}
    names = {item["name"] for item in db.storage.from_("menu-images").list(prefix.rstrip("/"))}
    assert names == {"fresh.jpg"}
    # 行は残る
    assert db.table("menus").select("image_path").eq("id", old_menu).execute().data == [{"image_path": old_path}]
    # 2回目は対象なし（削除済みを数えない）
    assert delete_expired_images(db, apply=True, now=now, path_prefix=prefix)["images_remaining"] == 0
