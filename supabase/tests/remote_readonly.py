"""03：適用先（クラウド）の読取専用チェック。データを書き込まない。

本番兼用の環境で、Supabase SDK・APIゲートウェイ経由の動作を確認する。
- サーバー用鍵：マスタの読取、公開ビューの読取、バケット設定の取得、書込前に失敗するRPC呼び出しのSQLSTATE
- 公開用キー（anon）：テーブル・ビュー・RPC・Storageが拒否されること
- 検証データが残っていないこと（データテーブルの件数）

環境変数（supabase/.env.local を読み込んで渡す。値は表示しない）：
    SUPABASE_URL          プロジェクトのURL（https://<ref>.supabase.co）
    SUPABASE_SECRET_KEY   サーバー用鍵（sb_secret_...）
    SUPABASE_ACCESS_TOKEN 公開用キーの取得に使用（CLI経由）

    set -a; source supabase/.env.local; set +a
    supabase/tests/.venv/bin/python supabase/tests/remote_readonly.py --project-ref <ref>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from postgrest.exceptions import APIError
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "supabase" / "node_modules" / ".bin" / "supabase"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not ok else ""))


def api_error(fn) -> APIError | None:
    try:
        fn()
    except APIError as exc:
        return exc
    return None


def base_url(project_ref: str) -> str:
    raw = os.environ["SUPABASE_URL"]
    parsed = urlparse(raw)
    expected_host = f"{project_ref}.supabase.co"
    if parsed.hostname != expected_host:
        print(f"refusing to run: SUPABASE_URL host does not match project ref {project_ref}")
        sys.exit(2)
    if parsed.path not in ("", "/"):
        print("WARNING: SUPABASE_URL has a path (e.g. /rest/v1/). Using the project base URL instead. "
              "Set SUPABASE_URL to https://<ref>.supabase.co for the API.")
    return f"https://{expected_host}"


def publishable_key(project_ref: str) -> str:
    out = subprocess.run([str(CLI), "projects", "api-keys", "--project-ref", project_ref, "-o", "json"],
                         cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    keys = json.loads(out.stdout[out.stdout.index("["):])
    for key in keys:
        if key.get("type") == "publishable" or str(key.get("api_key", "")).startswith("sb_publishable_"):
            return key["api_key"]
    print("no publishable key found")
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-ref", required=True)
    args = parser.parse_args()
    url = base_url(args.project_ref)
    svc = create_client(url, os.environ["SUPABASE_SECRET_KEY"])
    anon_headers = {"apikey": publishable_key(args.project_ref)}
    print(f"target: {url} (read-only)")

    # サーバー用鍵：読取
    allergens = svc.table("allergens").select("id,code,category,display_order").order("display_order").execute().data
    check("service: 29 allergens readable in display_order (9 required + 20 recommended)",
          len(allergens) == 29 and [a["display_order"] for a in allergens] == list(range(1, 30))
          and sum(a["category"] == "required" for a in allergens) == 9)
    dietary = svc.table("dietary_restrictions").select("id,code").order("id").execute().data
    check("service: 4 dietary restrictions readable",
          [d["code"] for d in dietary] == ["vegan", "vegetarian", "halal", "no_alcohol"], repr(dietary))
    for view in ("published_menus", "published_confirmation_answers", "published_dietary_answers"):
        rows = svc.table(view).select("*").limit(1).execute().data
        check(f"service: {view} readable", isinstance(rows, list))

    counts = {}
    for table in ("restaurants", "menus", "dishes", "confirmation_sessions", "confirmation_answers",
                  "confirmation_dietary_answers", "accounts", "account_allergens", "account_dietary_restrictions"):
        counts[table] = svc.table(table).select("*", count="exact", head=True).execute().count
    check("service: data tables are empty (verify.sql left nothing behind)", all(v == 0 for v in counts.values()),
          repr(counts))

    # サーバー用鍵：書込前に失敗するRPC呼び出し（引数名・SQLSTATE の確認）
    err = api_error(lambda: svc.rpc("complete_confirmation_session", {
        "p_menu_id": str(uuid.uuid4()), "p_analysis_token_hash": "0" * 64, "p_request_id": str(uuid.uuid4()),
        "p_answers": [], "p_dietary_answers": [], "p_publish_consent": False}).execute())
    check("service rpc: complete_confirmation_session unknown menu -> P0002 menu_not_found",
          err is not None and err.code == "P0002" and err.message == "menu_not_found", repr(err))
    err = api_error(lambda: svc.rpc("save_menu_analysis", {
        "p_restaurant_id": None, "p_image_path": "readonly-check/never-saved.jpg", "p_analysis_token_hash": "NOT-A-HASH",
        "p_dishes": [], "p_ai_model": "m", "p_prompt_version": "v4"}).execute())
    check("service rpc: save_menu_analysis invalid hash -> 22023 invalid_analysis_token_hash (nothing written)",
          err is not None and err.code == "22023" and err.message == "invalid_analysis_token_hash", repr(err))
    err = api_error(lambda: svc.rpc("save_menu_analysis", {
        "p_restaurant_id": None, "p_image_path": "readonly-check/never-saved.jpg", "p_analysis_token_hash": "0" * 64,
        "p_dishes": [], "p_ai_model": "m", "p_prompt_version": "v4", "p_account_id": str(uuid.uuid4())}).execute())
    check("service rpc: save_menu_analysis unknown owner -> P0002 account_not_found (nothing written)",
          err is not None and err.code == "P0002" and err.message == "account_not_found", repr(err))
    for fn, arg in (("replace_account_allergens", "p_allergen_ids"),
                    ("replace_account_dietary_restrictions", "p_dietary_restriction_ids")):
        err = api_error(lambda: svc.rpc(fn, {"p_account_id": str(uuid.uuid4()), arg: []}).execute())
        check(f"service rpc: {fn} unknown account -> P0002 account_not_found",
              err is not None and err.code == "P0002" and err.message == "account_not_found", repr(err))

    # Storage：バケット設定（サーバー用鍵）
    bucket = svc.storage.get_bucket("menu-images")
    check("storage: menu-images is private, 2 MiB, jpeg/png only",
          bucket.public is False and int(bucket.file_size_limit) == 2097152
          and sorted(bucket.allowed_mime_types or []) == ["image/jpeg", "image/png"],
          f"public={bucket.public} limit={bucket.file_size_limit} mime={bucket.allowed_mime_types}")

    # anon：すべて拒否
    with httpx.Client(timeout=20) as http:
        for path in ("menus?select=id", "accounts?select=id", "allergens?select=id", "published_menus?select=menu_id"):
            r = http.get(f"{url}/rest/v1/{path}", headers=anon_headers)
            body = r.json() if "json" in r.headers.get("content-type", "") else {}
            check(f"anon: GET {path.split('?')[0]} denied (42501)", isinstance(body, dict) and body.get("code") == "42501",
                  f"{r.status_code} {r.text[:100]}")
        for fn, payload in (("complete_confirmation_session", {
                                "p_menu_id": str(uuid.uuid4()), "p_analysis_token_hash": "0" * 64,
                                "p_request_id": str(uuid.uuid4()), "p_answers": [], "p_dietary_answers": [],
                                "p_publish_consent": False}),
                            ("save_menu_analysis", {
                                "p_restaurant_id": None, "p_image_path": "x", "p_analysis_token_hash": "x",
                                "p_dishes": [], "p_ai_model": "m", "p_prompt_version": "v4"}),
                            ("replace_account_allergens", {"p_account_id": str(uuid.uuid4()), "p_allergen_ids": []})):
            r = http.post(f"{url}/rest/v1/rpc/{fn}", headers=anon_headers, json=payload)
            check(f"anon: RPC {fn} denied (42501)", r.json().get("code") == "42501", f"{r.status_code} {r.text[:100]}")
        r = http.post(f"{url}/storage/v1/object/list/menu-images", headers=anon_headers, json={"prefix": ""})
        check("anon: storage list returns nothing", r.status_code != 200 or r.json() == [], f"{r.status_code}")
        r = http.get(f"{url}/storage/v1/object/public/menu-images/readonly-check.jpg")
        check("anon: public object URL is not served", r.status_code != 200, str(r.status_code))
        r = http.post(f"{url}/storage/v1/object/menu-images/readonly-check.jpg",
                      headers={**anon_headers, "content-type": "image/jpeg"}, content=b"\xff\xd8\xff\xd9")
        check("anon: storage upload denied", r.status_code not in (200, 201), str(r.status_code))

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
