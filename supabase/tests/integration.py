"""03の統合検証：Supabase SDK（supabase-py）経由のRPC・Storage、実時間の期限切れ、複数接続の並行実行。

verify.sql と違いデータをコミットするため、ローカル開発環境（supabase start）だけを対象にする。
接続先・鍵は `supabase status` から取得し、クラウドの秘密値は使わない。
作成したデータは実行ごとのタグで識別し、最後に削除する（DB行は所有者接続で、画像は Storage API で）。

    supabase/tests/.venv/bin/python supabase/tests/integration.py

終了コード：0＝全件成功、1＝失敗あり、2＝実行環境の不備。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psycopg
from postgrest.exceptions import APIError
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "supabase" / "node_modules" / ".bin" / "supabase"
BUCKET = "menu-images"
RUN = uuid.uuid4().hex[:10]
TAG = f"it-{RUN}"
ARGON = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not ok else ""))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def dish(name: str) -> dict:
    return {
        "name": name,
        "name_key": name.replace(" ", "").lower(),
        "translations": {"en": {"name": name, "description": "AI description"}},
        "price": 1200,
        "currency": "JPY",
        "ai_result": {"ingredients": [], "allergens": [], "dietary_restrictions": []},
    }


def local_status() -> dict:
    out = subprocess.run([str(CLI), "status", "-o", "json"], cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    status = json.loads(out.stdout[out.stdout.index("{"):])
    for key in ("API_URL", "DB_URL"):
        host = urlparse(status[key]).hostname
        if host not in ("127.0.0.1", "localhost"):
            print(f"refusing to run: {key} is not local ({host})")
            sys.exit(2)
    return status


def hs256_jwt(secret: str, claims: dict) -> str:
    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps(claims).encode())
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(signature)}"


def api_error(fn) -> APIError | None:
    try:
        fn()
    except APIError as exc:
        return exc
    return None


def rpc(client, name: str, params: dict):
    return client.rpc(name, params).execute().data


def db_connect(db_url: str, role: str | None = "service_role") -> psycopg.Connection:
    conn = psycopg.connect(db_url, autocommit=False)
    if role:
        conn.execute(f"set role {role}")
        conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 1. SDK経由のRPC4つ（引数名・戻り値・SQLSTATE）
# ---------------------------------------------------------------------------

def test_sdk_rpcs(svc, ctx: dict) -> None:
    restaurant = svc.table("restaurants").insert({"google_place_id": f"{TAG}-place"}).execute().data[0]
    ctx["restaurant_id"] = restaurant["id"]

    yes = svc.table("accounts").insert({
        "email": f"yes+{RUN}@example.com", "nickname": "Alex", "password_hash": ARGON,
        "publish_consent": True, "publish_consent_version": "2026-10-17-v1",
    }).execute().data[0]
    no = svc.table("accounts").insert({
        "email": f"no+{RUN}@example.com", "nickname": "Sam", "password_hash": ARGON,
        "publish_consent": False, "publish_consent_version": "2026-10-17-v1",
    }).execute().data[0]
    ctx["acc_yes"], ctx["acc_no"] = yes["id"], no["id"]
    check("sdk: register accounts with consent true/false and DB timestamps",
          yes["publish_consent"] is True and no["publish_consent"] is False and yes["publish_consent_recorded_at"])

    err = api_error(lambda: svc.table("accounts").insert({
        "email": f"YES+{RUN}@example.com".lower(), "nickname": "Dup", "password_hash": ARGON,
        "publish_consent": True, "publish_consent_version": "v1"}).execute())
    check("sdk: duplicate email -> 23505 accounts_email_key",
          err is not None and err.code == "23505" and "accounts_email_key" in (err.message or ""), repr(err))

    data = rpc(svc, "replace_account_allergens", {"p_account_id": yes["id"], "p_allergen_ids": [6, 4]})
    check("sdk: replace_account_allergens returns ascending list", data == [4, 6], repr(data))
    data = rpc(svc, "replace_account_dietary_restrictions", {"p_account_id": yes["id"], "p_dietary_restriction_ids": [4, 1]})
    check("sdk: replace_account_dietary_restrictions returns ascending list", data == [1, 4], repr(data))
    data = rpc(svc, "replace_account_allergens", {"p_account_id": yes["id"], "p_allergen_ids": []})
    check("sdk: replace with [] clears", data == [], repr(data))
    err = api_error(lambda: rpc(svc, "replace_account_allergens", {"p_account_id": yes["id"], "p_allergen_ids": [30]}))
    check("sdk: unknown allergen id -> 22023 invalid_allergen_ids",
          err is not None and err.code == "22023" and err.message == "invalid_allergen_ids", repr(err))
    err = api_error(lambda: rpc(svc, "replace_account_dietary_restrictions",
                                {"p_account_id": yes["id"], "p_dietary_restriction_ids": [1, 1]}))
    check("sdk: duplicate dietary id -> 22023 invalid_dietary_restriction_ids",
          err is not None and err.code == "22023" and err.message == "invalid_dietary_restriction_ids", repr(err))
    err = api_error(lambda: rpc(svc, "replace_account_allergens", {"p_account_id": str(uuid.uuid4()), "p_allergen_ids": [1]}))
    check("sdk: unknown account -> P0002 account_not_found",
          err is not None and err.code == "P0002" and err.message == "account_not_found", repr(err))

    # 解析保存：所有者あり（引数名 p_account_id）とゲスト（省略）
    menu_id = rpc(svc, "save_menu_analysis", {
        "p_restaurant_id": ctx["restaurant_id"], "p_image_path": f"{TAG}/owned.jpg",
        "p_analysis_token_hash": token_hash(f"{TAG}-owned"), "p_dishes": [dish("Shrimp tempura soba"), dish("Kitsune udon")],
        "p_ai_model": "gemini-test", "p_prompt_version": "v4", "p_account_id": yes["id"],
    })
    ctx["menu_owned"] = menu_id
    menu = svc.table("menus").select("account_id,user_publish_consent").eq("id", menu_id).execute().data[0]
    check("sdk: save_menu_analysis returns uuid and copies owner/consent",
          isinstance(menu_id, str) and menu["account_id"] == yes["id"] and menu["user_publish_consent"] is True, repr(menu))

    guest_id = rpc(svc, "save_menu_analysis", {
        "p_restaurant_id": None, "p_image_path": f"{TAG}/guest.jpg",
        "p_analysis_token_hash": token_hash(f"{TAG}-guest"), "p_dishes": [dish("Katsu curry")],
        "p_ai_model": "gemini-test", "p_prompt_version": "v4",
    })
    ctx["menu_guest"] = guest_id
    menu = svc.table("menus").select("account_id,user_publish_consent").eq("id", guest_id).execute().data[0]
    check("sdk: guest save (p_account_id omitted) -> owner NULL, consent false",
          menu["account_id"] is None and menu["user_publish_consent"] is False, repr(menu))

    err = api_error(lambda: rpc(svc, "save_menu_analysis", {
        "p_restaurant_id": None, "p_image_path": f"{TAG}/ghost.jpg", "p_analysis_token_hash": token_hash(f"{TAG}-ghost"),
        "p_dishes": [dish("X")], "p_ai_model": "m", "p_prompt_version": "v4", "p_account_id": str(uuid.uuid4())}))
    check("sdk: unknown owner -> P0002 account_not_found",
          err is not None and err.code == "P0002" and err.message == "account_not_found", repr(err))

    # 途中失敗（2件目の料理名が201文字）でメニューが残らない
    err = api_error(lambda: rpc(svc, "save_menu_analysis", {
        "p_restaurant_id": ctx["restaurant_id"], "p_image_path": f"{TAG}/partial.jpg",
        "p_analysis_token_hash": token_hash(f"{TAG}-partial"), "p_dishes": [dish("ok"), dish("x" * 201)],
        "p_ai_model": "m", "p_prompt_version": "v4"}))
    left = svc.table("menus").select("id").eq("image_path", f"{TAG}/partial.jpg").execute().data
    check("sdk: failing 2nd dish -> 23514 and no partial menu", err is not None and err.code == "23514" and left == [],
          repr(err))

    dishes = svc.table("dishes").select("id,position,version").eq("menu_id", menu_id).order("position").execute().data
    ctx["owned_dishes"] = [d["id"] for d in dishes]
    check("sdk: dishes come back in position order", [d["position"] for d in dishes] == [1, 2])

    params = {
        "p_menu_id": menu_id, "p_analysis_token_hash": token_hash(f"{TAG}-owned"), "p_request_id": str(uuid.uuid4()),
        "p_answers": [{"dish_id": d, "allergen_id": 4, "answer": "contains"} for d in ctx["owned_dishes"]],
        "p_dietary_answers": [{"dish_id": d, "dietary_restriction_id": 1, "answer": "unknown"} for d in ctx["owned_dishes"]],
        "p_publish_consent": True,
    }
    first = rpc(svc, "complete_confirmation_session", params)
    check("sdk: complete_confirmation_session returns a single object {session_id, confirmed_at, replayed}",
          isinstance(first, dict) and set(first) == {"session_id", "confirmed_at", "replayed"} and first["replayed"] is False,
          repr(first))
    ctx["owned_session"] = first["session_id"]
    reordered = dict(params, p_answers=list(reversed(params["p_answers"])),
                     p_dietary_answers=list(reversed(params["p_dietary_answers"])))
    again = rpc(svc, "complete_confirmation_session", reordered)
    check("sdk: reordered resend -> replayed=true with same session",
          again["replayed"] is True and again["session_id"] == first["session_id"]
          and again["confirmed_at"] == first["confirmed_at"], repr(again))
    err = api_error(lambda: rpc(svc, "complete_confirmation_session", dict(params, p_publish_consent=False)))
    check("sdk: same request_id, different consent -> 40001 request_id_conflict",
          err is not None and err.code == "40001" and err.message == "request_id_conflict", repr(err))
    err = api_error(lambda: rpc(svc, "complete_confirmation_session",
                                dict(params, p_request_id=str(uuid.uuid4()), p_analysis_token_hash=token_hash(f"{TAG}-guest"))))
    check("sdk: other menu's token -> 28000 invalid_analysis_token",
          err is not None and err.code == "28000" and err.message == "invalid_analysis_token", repr(err))
    err = api_error(lambda: rpc(svc, "complete_confirmation_session", dict(params, p_menu_id=str(uuid.uuid4()))))
    check("sdk: unknown menu -> P0002 menu_not_found",
          err is not None and err.code == "P0002" and err.message == "menu_not_found", repr(err))
    err = api_error(lambda: rpc(svc, "complete_confirmation_session",
                                dict(params, p_request_id=str(uuid.uuid4()), p_answers=[], p_dietary_answers=[])))
    check("sdk: both arrays empty -> 22023 answers_invalid",
          err is not None and err.code == "22023" and err.message == "answers_invalid", repr(err))
    err = api_error(lambda: rpc(svc, "complete_confirmation_session",
                                dict(params, p_request_id=str(uuid.uuid4()),
                                     p_answers=[{"dish_id": ctx["owned_dishes"][0], "allergen_id": 4, "answer": None}],
                                     p_dietary_answers=[])))
    check("sdk: null answer -> 22023 answers_invalid",
          err is not None and err.code == "22023" and err.message == "answers_invalid", repr(err))

    public = svc.table("published_confirmation_answers").select("session_id,allergen_id,answer") \
        .eq("menu_id", menu_id).execute().data
    check("sdk: consenting owner + store + staff consent is readable from the public view",
          len(public) == 2 and all(r["session_id"] == first["session_id"] for r in public), repr(public))


# ---------------------------------------------------------------------------
# 2. 権限（anon・authenticated）
# ---------------------------------------------------------------------------

def test_client_roles(status: dict, ctx: dict) -> None:
    url = status["API_URL"]
    anon_headers = {"apikey": status["PUBLISHABLE_KEY"]}
    jwt = hs256_jwt(status["JWT_SECRET"], {
        "role": "authenticated", "aud": "authenticated", "sub": str(uuid.uuid4()),
        "iat": int(time.time()), "exp": int(time.time()) + 600,
    })
    auth_headers = {"apikey": status["PUBLISHABLE_KEY"], "Authorization": f"Bearer {jwt}"}
    with httpx.Client(timeout=20) as http:
        for who, headers in (("anon", anon_headers), ("authenticated", auth_headers)):
            codes = {}
            for path in ("menus?select=id", "accounts?select=id", "published_menus?select=menu_id"):
                r = http.get(f"{url}/rest/v1/{path}", headers=headers)
                codes[path] = (r.status_code, r.json().get("code") if r.headers.get("content-type", "").startswith("application/json") and isinstance(r.json(), dict) else None)
            check(f"{who}: REST select on tables/views is denied (42501)",
                  all(c[1] == "42501" for c in codes.values()), repr(codes))
            r = http.post(f"{url}/rest/v1/rpc/complete_confirmation_session", headers=headers, json={
                "p_menu_id": ctx["menu_owned"], "p_analysis_token_hash": token_hash(f"{TAG}-owned"),
                "p_request_id": str(uuid.uuid4()), "p_answers": [], "p_dietary_answers": [], "p_publish_consent": True})
            check(f"{who}: RPC execution is denied (42501)", r.json().get("code") == "42501", f"{r.status_code} {r.text[:120]}")
            r = http.post(f"{url}/rest/v1/rpc/replace_account_allergens", headers=headers,
                          json={"p_account_id": ctx["acc_yes"], "p_allergen_ids": []})
            check(f"{who}: replace RPC is denied (42501)", r.json().get("code") == "42501", f"{r.status_code} {r.text[:120]}")
    ctx["authenticated_headers"] = auth_headers
    ctx["anon_headers"] = anon_headers


# ---------------------------------------------------------------------------
# 3. Storage（実際の Storage API）
# ---------------------------------------------------------------------------

def test_storage(svc, status: dict, ctx: dict) -> None:
    url = status["API_URL"]
    bucket = svc.storage.from_(BUCKET)
    path = f"{TAG}/owned.jpg"  # menus.image_path と同じパス

    bucket.upload(path, JPEG, {"content-type": "image/jpeg"})
    check("storage: server key uploads a JPEG", bucket.download(path) == JPEG)
    bucket.upload(f"{TAG}/guest.jpg", JPEG, {"content-type": "image/png"})
    check("storage: server key uploads a PNG-typed object", True)

    def upload_error(name: str, data: bytes, content_type: str) -> str | None:
        try:
            bucket.upload(f"{TAG}/{name}", data, {"content-type": content_type})
        except Exception as exc:  # storage3 の例外型はバージョンで異なる
            return str(exc)
        return None

    err = upload_error("anim.gif", b"GIF89a" + b"\x00" * 16, "image/gif")
    check("storage: image/gif is rejected by bucket MIME restriction", err is not None, repr(err))
    err = upload_error("big.jpg", b"\xff\xd8" + b"\x00" * 2_097_151, "image/jpeg")
    check("storage: 2,097,153 bytes is rejected by bucket size limit", err is not None, repr(err))
    err = upload_error("limit.jpg", b"\xff\xd8" + b"\x00" * 2_097_150, "image/jpeg")
    check("storage: exactly 2,097,152 bytes is accepted", err is None, repr(err))

    with httpx.Client(timeout=20) as http:
        r = http.get(f"{url}/storage/v1/object/public/{BUCKET}/{path}")
        check("storage: public URL does not serve the image", r.status_code != 200 and r.content != JPEG, str(r.status_code))
        for who in ("anon", "authenticated"):
            headers = ctx[f"{who}_headers"]
            r = http.get(f"{url}/storage/v1/object/{BUCKET}/{path}", headers=headers)
            check(f"storage: {who} cannot download the image", r.status_code != 200 and r.content != JPEG, str(r.status_code))
            r = http.post(f"{url}/storage/v1/object/list/{BUCKET}", headers=headers, json={"prefix": TAG})
            listed = r.json() if r.status_code == 200 else None
            check(f"storage: {who} cannot list objects", r.status_code != 200 or listed == [], f"{r.status_code} {r.text[:80]}")
            r = http.post(f"{url}/storage/v1/object/{BUCKET}/{TAG}/{who}.jpg",
                          headers={**headers, "content-type": "image/jpeg"}, content=JPEG)
            check(f"storage: {who} cannot upload", r.status_code not in (200, 201), str(r.status_code))
            r = http.post(f"{url}/storage/v1/object/sign/{BUCKET}/{path}", headers=headers, json={"expiresIn": 60})
            check(f"storage: {who} cannot create a signed URL", r.status_code != 200, str(r.status_code))

    # 公開確認があるメニューでも画像は公開されない（上で同意ありの確認を保存済み）
    with httpx.Client(timeout=20) as http:
        r = http.get(f"{url}/storage/v1/object/public/{BUCKET}/{path}")
    check("storage: image of a published menu is still private", r.status_code != 200, str(r.status_code))

    # Storage APIで削除しても、メニュー・料理・回答・本人履歴は残る
    bucket.remove([path])
    try:
        bucket.download(path)
        gone = False
    except Exception:
        gone = True
    rows = svc.table("menus").select("id,image_path,dishes(id),confirmation_sessions(id,confirmation_answers(id))") \
        .eq("id", ctx["menu_owned"]).eq("account_id", ctx["acc_yes"]).execute().data
    check("storage: delete via Storage API removes the object", gone)
    check("storage: menu, dishes, answers and own history remain after image deletion",
          len(rows) == 1 and len(rows[0]["dishes"]) == 2
          and len(rows[0]["confirmation_sessions"][0]["confirmation_answers"]) == 2, repr(rows))


# ---------------------------------------------------------------------------
# 4. 実時間の期限切れ
# ---------------------------------------------------------------------------

def test_real_expiry(svc, ctx: dict) -> None:
    token = token_hash(f"{TAG}-expiring")
    expires = (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat()
    menu_id = rpc(svc, "save_menu_analysis", {
        "p_restaurant_id": ctx["restaurant_id"], "p_image_path": f"{TAG}/expiring.jpg", "p_analysis_token_hash": token,
        "p_dishes": [dish("Soba")], "p_ai_model": "gemini-test", "p_prompt_version": "v4",
        "p_analysis_expires_at": expires, "p_account_id": ctx["acc_no"],
    })
    dish_id = svc.table("dishes").select("id").eq("menu_id", menu_id).execute().data[0]["id"]
    params = {"p_menu_id": menu_id, "p_analysis_token_hash": token, "p_request_id": str(uuid.uuid4()),
              "p_answers": [{"dish_id": dish_id, "allergen_id": 6, "answer": "contains"}],
              "p_dietary_answers": [], "p_publish_consent": False}
    first = rpc(svc, "complete_confirmation_session", params)
    check("expiry: confirmation before expiry succeeds", first["replayed"] is False)
    time.sleep(4)
    err = api_error(lambda: rpc(svc, "complete_confirmation_session", dict(params, p_request_id=str(uuid.uuid4()))))
    check("expiry: new confirmation after expiry -> P0003 analysis_expired",
          err is not None and err.code == "P0003" and err.message == "analysis_expired", repr(err))
    err = api_error(lambda: rpc(svc, "complete_confirmation_session", params))
    check("expiry: resend after expiry -> P0003", err is not None and err.code == "P0003", repr(err))
    rows = svc.table("menus").select("id,confirmation_sessions(id)").eq("id", menu_id).eq("account_id", ctx["acc_no"]).execute().data
    check("expiry: own history still has the menu and its confirmation",
          len(rows) == 1 and len(rows[0]["confirmation_sessions"]) == 1, repr(rows))


# ---------------------------------------------------------------------------
# 5. 複数接続の並行実行
# ---------------------------------------------------------------------------

def run_concurrently(db_url: str, calls: list[tuple[str, tuple]]) -> list[tuple[str, object]]:
    """各呼び出しを別接続（service_role）で同時に開始し、(ok|error_code, 結果/メッセージ) を返す。"""
    conns = [db_connect(db_url) for _ in calls]
    barrier = threading.Barrier(len(calls))
    out: list[tuple[str, object]] = [("", None)] * len(calls)

    def worker(i: int) -> None:
        sql, args = calls[i]
        conn = conns[i]
        try:
            barrier.wait()
            with conn.cursor() as cur:
                cur.execute(sql, args)
                row = cur.fetchone()
            conn.commit()
            out[i] = ("ok", row)
        except psycopg.Error as exc:
            conn.rollback()
            out[i] = (exc.sqlstate or "?", exc.diag.message_primary)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(calls))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for c in conns:
        c.close()
    return out


CONFIRM_SQL = ("select session_id, replayed from public.complete_confirmation_session("
               "%s, %s, %s, %s::jsonb, %s::jsonb, %s)")


def new_menu(svc, ctx: dict, key: str, dishes: int = 1, account: str | None = None) -> tuple[str, str, list[str]]:
    token = token_hash(f"{TAG}-{key}")
    menu_id = rpc(svc, "save_menu_analysis", {
        "p_restaurant_id": ctx["restaurant_id"], "p_image_path": f"{TAG}/{key}.jpg", "p_analysis_token_hash": token,
        "p_dishes": [dish(f"Dish {i}") for i in range(1, dishes + 1)], "p_ai_model": "gemini-test",
        "p_prompt_version": "v4", "p_account_id": account,
    })
    ids = [d["id"] for d in svc.table("dishes").select("id,position").eq("menu_id", menu_id).order("position").execute().data]
    return menu_id, token, ids


def test_concurrency(svc, status: dict, ctx: dict) -> None:
    db_url = status["DB_URL"]
    admin = db_connect(db_url, role=None)

    def count(sql: str, *args) -> int:
        with admin.cursor() as cur:
            cur.execute(sql, args)
            value = cur.fetchone()[0]
        admin.commit()
        return value

    # 5-1. 異なる request_id を8接続から同時送信 → 確認は5件まで、失敗分の回答は残らない
    for round_no in range(3):
        menu_id, token, dish_ids = new_menu(svc, ctx, f"limit{round_no}", dishes=2)
        calls = []
        for _ in range(8):
            answers = [{"dish_id": d, "allergen_id": a, "answer": "contains"} for d in dish_ids for a in (1, 4)]
            calls.append((CONFIRM_SQL, (menu_id, token, str(uuid.uuid4()), json.dumps(answers), "[]", False)))
        out = run_concurrently(db_url, calls)
        ok = sum(1 for s, _ in out if s == "ok")
        limited = sum(1 for s, r in out if s == "22023" and r == "confirmation_limit_reached")
        sessions = count("select count(*) from public.confirmation_sessions where menu_id = %s", menu_id)
        answers = count("select count(*) from public.confirmation_answers a join public.confirmation_sessions s"
                        " on s.id = a.session_id where s.menu_id = %s", menu_id)
        check(f"concurrency: 8 parallel new confirmations -> 5 saved, 3 limited (round {round_no + 1})",
              ok == 5 and limited == 3 and sessions == 5 and answers == 5 * 4, f"ok={ok} limited={limited} "
              f"sessions={sessions} answers={answers} out={out}")

    # 5-2. 同一 request_id・同内容を6接続から同時送信 → 1件だけ作成、残りは同じIDで replayed
    menu_id, token, dish_ids = new_menu(svc, ctx, "replay")
    request_id = str(uuid.uuid4())
    answers = json.dumps([{"dish_id": dish_ids[0], "allergen_id": 4, "answer": "unknown"}])
    dietary = json.dumps([{"dish_id": dish_ids[0], "dietary_restriction_id": 3, "answer": "unknown"}])
    out = run_concurrently(db_url, [(CONFIRM_SQL, (menu_id, token, request_id, answers, dietary, True))] * 6)
    ids = {r[0] for s, r in out if s == "ok"}
    replayed = sorted(r[1] for s, r in out if s == "ok")
    check("concurrency: same request_id x6 -> one session, five replays",
          all(s == "ok" for s, _ in out) and len(ids) == 1 and replayed == [False] + [True] * 5
          and count("select count(*) from public.confirmation_sessions where menu_id = %s", menu_id) == 1, repr(out))

    # 5-3. 同一 request_id・異なる内容／店員同意を同時送信 → 1件成功、他は 40001
    menu_id, token, dish_ids = new_menu(svc, ctx, "conflict")
    request_id = str(uuid.uuid4())
    calls = [
        (CONFIRM_SQL, (menu_id, token, request_id,
                       json.dumps([{"dish_id": dish_ids[0], "allergen_id": 4, "answer": "contains"}]), "[]", True)),
        (CONFIRM_SQL, (menu_id, token, request_id,
                       json.dumps([{"dish_id": dish_ids[0], "allergen_id": 4, "answer": "not_contains"}]), "[]", True)),
        (CONFIRM_SQL, (menu_id, token, request_id,
                       json.dumps([{"dish_id": dish_ids[0], "allergen_id": 4, "answer": "contains"}]), "[]", False)),
    ]
    out = run_concurrently(db_url, calls)
    states = sorted(s for s, _ in out)
    check("concurrency: same request_id with different content/consent -> 1 ok, others 40001",
          states == ["40001", "40001", "ok"]
          and count("select count(*) from public.confirmation_sessions where menu_id = %s", menu_id) == 1
          and count("select count(*) from public.confirmation_answers a join public.confirmation_sessions s"
                    " on s.id = a.session_id where s.menu_id = %s", menu_id) == 1, repr(out))

    # 5-4. 本人設定の同時置換 → どれか1つの完全な集合だけが残る（混合・重複・削除だけの状態なし）
    for kind, fn, table, column, sets in (
        ("allergens", "replace_account_allergens", "account_allergens", "allergen_id",
         [[1, 2, 3], [4, 5], [6], [7, 8, 9, 10], [], [11, 12, 13, 14, 15], [29], [2, 4, 6, 8]]),
        ("dietary", "replace_account_dietary_restrictions", "account_dietary_restrictions", "dietary_restriction_id",
         [[1], [2, 3], [4], [1, 2, 3, 4], [], [3], [1, 4], [2]]),
    ):
        mixed = []
        for round_no in range(5):
            sql = f"select public.{fn}(%s, %s::jsonb)"
            out = run_concurrently(db_url, [(sql, (ctx["acc_yes"], json.dumps(s))) for s in sets])
            with admin.cursor() as cur:
                cur.execute(f"select coalesce(array_agg({column} order by {column}), '{{}}') from public.{table}"
                            f" where account_id = %s", (ctx["acc_yes"],))
                final = list(cur.fetchone()[0])
            admin.commit()
            if not (all(s == "ok" for s, _ in out) and final in [sorted(s) for s in sets]):
                mixed.append((round_no, final, out))
        check(f"concurrency: parallel replace of {kind} leaves exactly one submitted set (5 rounds x 8)",
              not mixed, repr(mixed))
        others = count(f"select count(*) from public.{table} where account_id = %s", ctx["acc_no"])
        check(f"concurrency: parallel replace of {kind} does not touch other accounts", others == 0, str(others))

    admin.close()


# ---------------------------------------------------------------------------
# 後始末（このタグのデータだけを削除する）
# ---------------------------------------------------------------------------

def cleanup(svc, status: dict) -> None:
    try:
        bucket = svc.storage.from_(BUCKET)
        names = [f"{TAG}/{o['name']}" for o in bucket.list(TAG)]
        if names:
            bucket.remove(names)
    except Exception as exc:
        print(f"[WARN] storage cleanup: {exc}")
    with psycopg.connect(status["DB_URL"]) as conn, conn.cursor() as cur:
        menus = "select id from public.menus where image_path like %(p)s"
        sessions = f"select id from public.confirmation_sessions where menu_id in ({menus})"
        cur.execute(f"delete from public.confirmation_dietary_answers where session_id in ({sessions})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.confirmation_answers where session_id in ({sessions})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.confirmation_sessions where menu_id in ({menus})", {"p": f"{TAG}/%"})
        cur.execute(f"delete from public.dishes where menu_id in ({menus})", {"p": f"{TAG}/%"})
        cur.execute("delete from public.menus where image_path like %(p)s", {"p": f"{TAG}/%"})
        cur.execute("delete from public.restaurants where google_place_id like %(p)s", {"p": f"{TAG}-%"})
        cur.execute("delete from public.accounts where email like %(p)s", {"p": f"%+{RUN}@example.com"})
        cur.execute(
            "select (select count(*) from public.menus where image_path like %(p)s)"
            " + (select count(*) from public.accounts where email like %(e)s)"
            " + (select count(*) from public.restaurants where google_place_id like %(r)s)",
            {"p": f"{TAG}/%", "e": f"%+{RUN}@example.com", "r": f"{TAG}-%"})
        left = cur.fetchone()[0]
    left_objects = svc.storage.from_(BUCKET).list(TAG)
    check("cleanup: test rows and storage objects removed", left == 0 and not left_objects,
          f"rows={left} objects={len(left_objects)}")


def main() -> int:
    status = local_status()
    svc = create_client(status["API_URL"], status["SECRET_KEY"])
    ctx: dict = {}
    print(f"target: local ({status['API_URL']}), run tag: {TAG}")
    try:
        for test in (lambda: test_sdk_rpcs(svc, ctx),
                     lambda: test_client_roles(status, ctx),
                     lambda: test_storage(svc, status, ctx),
                     lambda: test_real_expiry(svc, ctx),
                     lambda: test_concurrency(svc, status, ctx)):
            test()
    except Exception:
        check("unexpected exception", False, traceback.format_exc())
    finally:
        cleanup(svc, status)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
