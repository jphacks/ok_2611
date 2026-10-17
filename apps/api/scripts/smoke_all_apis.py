"""docs/api.md の全17操作を、起動中のAPIに対して順に実行して確認する（外部から呼ぶスモークテスト）。

  # 書き込みなし（公開URL・本番兼用DBでも可）：API 1・2・3・7・13と、書き込まないエラー応答
  .venv/bin/python scripts/smoke_all_apis.py https://meelyze-api.vercel.app
  # 書き込みあり（全17操作）。登録・解析・確認・本人設定を実際に保存する。ローカルDBに接続したAPIでだけ使う
  .venv/bin/python scripts/smoke_all_apis.py http://127.0.0.1:8765 --allow-writes

- 各応答のステータスを docs/api.md の定義と照合し、成功応答を contracts/openapi.yaml のスキーマ（JSON Schema 2020-12）で検証する。
- 解析にはPillowで描いた英語のメニュー画像を使う（`--image` で差し替え可）。GeminiとPlacesは接続先のAPIの設定に従う。
- 書き込みモードでは、作成したアカウントのメールアドレスとメニューIDを最後に表示する（後片付け用。トークン・パスワードは表示しない）。
- 標準ライブラリのHTTPクライアントだけを使い、APIのコードはimportしない（実際のHTTPで確認するため）。
"""

import argparse
import io
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

API_DIR = Path(__file__).resolve().parent.parent
CONTRACT = API_DIR.parent.parent / "contracts" / "openapi.yaml"
LAT, LNG = 35.6812, 139.7671  # 東京駅付近（テスト用の公開地点）


class _JsonLikeLoader(yaml.SafeLoader):
    pass


_JsonLikeLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
SPEC = yaml.load(CONTRACT.read_text(encoding="utf-8"), Loader=_JsonLikeLoader)


@dataclass
class Response:
    status: int
    headers: dict
    body: object
    seconds: float


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        (self.passed if ok else self.failed).append(label + ("" if ok else f" — {detail}"))
        print(("PASS " if ok else "FAIL ") + label + ("" if ok else f" — {detail}"), flush=True)
        return ok


def request(base: str, method: str, path: str, *, token=None, json_body=None, multipart=None, headers=None) -> Response:
    url = base.rstrip("/") + "/api/v1" + path
    data = None
    hdrs = dict(headers or {})
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    if multipart is not None:
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in multipart:
            if isinstance(value, tuple):
                filename, content, ctype = value
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n"
                )
            else:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            status, raw, res_headers = res.status, res.read(), dict(res.headers)
    except urllib.error.HTTPError as exc:
        status, raw, res_headers = exc.code, exc.read(), dict(exc.headers)
    seconds = time.monotonic() - start
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = raw[:200]
    return Response(status, {k.lower(): v for k, v in res_headers.items()}, body, seconds)


def schema_errors(instance, path: str, method: str, status: int) -> str | None:
    try:
        schema = SPEC["paths"][path][method]["responses"][str(status)]["content"]["application/json"]["schema"]
    except KeyError:
        return f"契約に {method.upper()} {path} {status} の応答がない"
    errors = sorted(Draft202012Validator({"components": SPEC["components"], **schema}).iter_errors(instance), key=str)
    return None if not errors else errors[0].message[:200]


def expect(report: Report, label: str, res: Response, status: int, contract: tuple[str, str] | None = None,
           code: str | None = None, no_store: bool | None = None) -> bool:
    ok = report.check(f"{label}：{status}", res.status == status, f"実際は {res.status} {json.dumps(res.body, ensure_ascii=False)[:200]}")
    if ok and contract:
        error = schema_errors(res.body, contract[0], contract[1], status)
        ok = report.check(f"{label}：契約のスキーマ", error is None, error or "")
    if ok and code:
        actual = (res.body or {}).get("error", {}).get("code") if isinstance(res.body, dict) else None
        ok = report.check(f"{label}：code={code}", actual == code, f"実際は {actual}")
    if ok and no_store is not None:
        ok = report.check(f"{label}：Cache-Control", (res.headers.get("cache-control") == "no-store") == no_store,
                          f"実際は {res.headers.get('cache-control')}")
    return ok


def menu_image() -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    for i, line in enumerate(["MENU", "Shrimp tempura soba ..... 1,200 yen", "Kake soba ..... 700 yen",
                              "Oyakodon (egg, chicken) ..... 950 yen"]):
        draw.text((40, 40 + i * 110), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def blank_image() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), "white").save(buffer, "JPEG")
    return buffer.getvalue()


def run_read_only(base: str, report: Report) -> str | None:
    res = request(base, "GET", "/health")
    expect(report, "API 1 GET /health", res, 200, ("/health", "get"))
    report.check("API 1：本文", res.body == {"status": "ok"}, str(res.body))
    res = request(base, "GET", "/allergens")
    if expect(report, "API 2 GET /allergens", res, 200, ("/allergens", "get")):
        report.check("API 2：29品目・表示順", [a["display_order"] for a in res.body["allergens"]] == list(range(1, 30)))
    res = request(base, "GET", "/dietary-restrictions")
    if expect(report, "API 13 GET /dietary-restrictions", res, 200, ("/dietary-restrictions", "get")):
        report.check("API 13：4種・ID順", [d["id"] for d in res.body["dietary_restrictions"]] == [1, 2, 3, 4])
    res = request(base, "GET", f"/places/nearby?lat={LAT}&lng={LNG}")
    place_id = None
    if expect(report, "API 3 GET /places/nearby", res, 200, ("/places/nearby", "get"), no_store=True):
        places = res.body["places"]
        report.check("API 3：最大20件・距離順", len(places) <= 20 and [p["distance_m"] for p in places] == sorted(p["distance_m"] for p in places))
        place_id = places[0]["google_place_id"] if places else None
    if place_id:
        res = request(base, "GET", f"/places/{place_id}/public-menus?allergen_ids=4,1&dietary_restriction_ids=4")
        expect(report, "API 7 GET /places/{id}/public-menus", res, 200, ("/places/{google_place_id}/public-menus", "get"), no_store=True)

    # 書き込まないエラー応答（API仕様の「エラー」）
    zero = "00000000-0000-4000-8000-000000000000"
    expect(report, "共通：未定義クエリ", request(base, "GET", "/allergens?foo=1"), 422, code="validation_error", no_store=True)
    expect(report, "共通：locale=ja", request(base, "GET", "/allergens?locale=ja"), 422, code="validation_error")
    expect(report, "API 3：範囲外の座標", request(base, "GET", "/places/nearby?lat=91&lng=0"), 422, code="validation_error")
    expect(report, "API 5：トークンなし", request(base, "GET", f"/menus/{zero}"), 401, code="unauthorized")
    expect(report, "API 5：存在しないメニュー", request(base, "GET", f"/menus/{zero}", token="x"), 404, code="not_found")
    expect(report, "API 6：トークンなし", request(base, "POST", f"/menus/{zero}/confirmations", json_body={}), 401, code="unauthorized")
    expect(report, "API 7：重複ID", request(base, "GET", "/places/x/public-menus?allergen_ids=4,4"), 422, code="invalid_allergen_ids")
    expect(report, "API 9：存在しないメール", request(base, "POST", "/auth/login",
           json_body={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.invalid", "password": "wrong-password"}), 401, code="invalid_credentials")
    for method, path in (("GET", "/me"), ("GET", "/me/allergens"), ("GET", "/me/dietary-restrictions"), ("GET", "/me/menus"), ("GET", f"/me/menus/{zero}")):
        expect(report, f"{path}：トークンなし", request(base, method, path), 401, code="unauthorized")
    expect(report, "API 10：解析用トークンの形式", request(base, "GET", "/me", token=secrets.token_urlsafe(32)), 401, code="unauthorized")
    gif = io.BytesIO()
    from PIL import Image

    Image.new("RGB", (4, 4)).save(gif, "GIF")
    expect(report, "API 4：GIF", request(base, "POST", "/menus/analyze", multipart=[("image", ("a.gif", gif.getvalue(), "image/gif"))]),
           415, code="unsupported_image_type")
    res = request(base, "POST", "/menus/analyze", multipart=[("image", ("blank.jpg", blank_image(), "image/jpeg"))])
    expect(report, "API 4：料理のない画像（Geminiまで到達、保存しない）", res, 422, code="unreadable_menu")
    print(f"  （料理のない画像の解析：{res.seconds:.1f}秒）")
    return place_id


def run_writes(base: str, report: Report, place_id: str | None, image: bytes) -> dict:
    created: dict = {"emails": [], "menu_ids": []}
    email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
    password = secrets.token_urlsafe(16)
    created["emails"].append(email)

    res = request(base, "POST", "/auth/register",
                  json_body={"email": f"  {email.upper()} ", "nickname": " Smoke ", "password": password, "publish_consent": True})
    if not expect(report, "API 8 POST /auth/register", res, 201, ("/auth/register", "post"), no_store=True):
        return created
    report.check("API 8：メールの正規化", res.body["account"]["email"] == email)
    expect(report, "API 8：重複メール", request(base, "POST", "/auth/register",
           json_body={"email": email, "nickname": "Smoke", "password": password, "publish_consent": False}), 409, code="email_already_registered")
    res = request(base, "POST", "/auth/login", json_body={"email": email, "password": password})
    expect(report, "API 9 POST /auth/login", res, 200, ("/auth/login", "post"))
    token = res.body["access_token"]
    expect(report, "API 9：誤ったパスワード", request(base, "POST", "/auth/login", json_body={"email": email, "password": password + "x"}),
           401, code="invalid_credentials")

    expect(report, "API 10 GET /me", request(base, "GET", "/me", token=token), 200, ("/me", "get"), no_store=True)
    res = request(base, "PUT", "/me/allergens", token=token, json_body={"allergen_ids": [6, 4]})
    if expect(report, "API 12 PUT /me/allergens", res, 200, ("/me/allergens", "put")):
        report.check("API 12：昇順", res.body == {"allergen_ids": [4, 6]})
    res = request(base, "GET", "/me/allergens", token=token)
    expect(report, "API 11 GET /me/allergens", res, 200, ("/me/allergens", "get"))
    report.check("API 11：置換後の内容", res.body == {"allergen_ids": [4, 6]})
    expect(report, "API 12：未知ID", request(base, "PUT", "/me/allergens", token=token, json_body={"allergen_ids": [30]}), 422, code="invalid_allergen_ids")
    res = request(base, "PUT", "/me/dietary-restrictions", token=token, json_body={"dietary_restriction_ids": [4, 1]})
    expect(report, "API 15 PUT /me/dietary-restrictions", res, 200, ("/me/dietary-restrictions", "put"))
    res = request(base, "GET", "/me/dietary-restrictions", token=token)
    expect(report, "API 14 GET /me/dietary-restrictions", res, 200, ("/me/dietary-restrictions", "get"))
    report.check("API 14：置換後の内容", res.body == {"dietary_restriction_ids": [1, 4]})

    fields = [("image", ("menu.jpg", image, "image/jpeg")), ("allergen_ids", "4"), ("allergen_ids", "1"), ("dietary_restriction_ids", "4")]
    if place_id:
        fields.append(("google_place_id", place_id))
    res = request(base, "POST", "/menus/analyze", token=token, multipart=fields)
    print(f"  （解析：{res.seconds:.1f}秒）")
    if not expect(report, "API 4 POST /menus/analyze", res, 201, ("/menus/analyze", "post"), no_store=True):
        return created
    menu = res.body
    created["menu_ids"].append(menu["menu_id"])
    report.check("API 4：料理を読み取り", len(menu["dishes"]) >= 1)
    report.check("API 4：今回の回答はnull", all(a["current_answer"] is None for d in menu["dishes"] for a in d["allergens"]))
    print("  料理：" + ", ".join(d["display_name"] for d in menu["dishes"]))
    analysis_token = menu["analysis_token"]

    res = request(base, "GET", f"/menus/{menu['menu_id']}?allergen_ids=4,1&dietary_restriction_ids=4", token=analysis_token)
    expect(report, "API 5 GET /menus/{id}", res, 200, ("/menus/{menu_id}", "get"), no_store=True)
    report.check("API 5：トークンを返さない", "analysis_token" not in res.body)
    expect(report, "API 5：アカウント用トークンでは不可", request(base, "GET", f"/menus/{menu['menu_id']}", token=token), 401, code="invalid_analysis_token")

    dish_id = menu["dishes"][0]["dish_id"]
    body = {
        "request_id": str(uuid.uuid4()),
        "answers": [{"dish_id": dish_id, "allergen_id": 4, "answer": "contains"},
                    {"dish_id": dish_id, "allergen_id": 1, "answer": "does_not_contain"}],
        "dietary_answers": [{"dish_id": dish_id, "dietary_restriction_id": 4, "answer": "unknown"}],
        "publish_consent": True,
    }
    res = request(base, "POST", f"/menus/{menu['menu_id']}/confirmations", token=analysis_token, json_body=body)
    if expect(report, "API 6 POST /menus/{id}/confirmations", res, 201, ("/menus/{menu_id}/confirmations", "post"), no_store=True):
        report.check("API 6：公開判定（店舗あり・両方同意）", res.body["is_public"] is bool(place_id))
    res = request(base, "POST", f"/menus/{menu['menu_id']}/confirmations", token=analysis_token, json_body=body)
    expect(report, "API 6：同じ内容の再送", res, 200, ("/menus/{menu_id}/confirmations", "post"))
    expect(report, "API 6：同じIDで違う内容", request(base, "POST", f"/menus/{menu['menu_id']}/confirmations", token=analysis_token,
           json_body={**body, "publish_consent": False}), 409, code="request_id_conflict")
    expect(report, "API 6：旧値 not_contains", request(base, "POST", f"/menus/{menu['menu_id']}/confirmations", token=analysis_token,
           json_body={**body, "request_id": str(uuid.uuid4()), "answers": [{"dish_id": dish_id, "allergen_id": 4, "answer": "not_contains"}],
                      "dietary_answers": []}), 422, code="answers_invalid")

    res = request(base, "GET", f"/menus/{menu['menu_id']}?allergen_ids=4", token=analysis_token)
    shrimp = res.body["dishes"][0]["allergens"][0] if res.status == 200 else {}
    report.check("API 5：確認後は今回の回答を反映", (shrimp.get("current_answer") or {}).get("answer") == "contains", str(shrimp.get("current_answer")))

    if place_id:
        res = request(base, "GET", f"/places/{place_id}/public-menus?allergen_ids=4")
        expect(report, "API 7：公開後の集計", res, 200, ("/places/{google_place_id}/public-menus", "get"))
        names = {d["name_key"] for d in res.body.get("dishes", [])} if res.status == 200 else set()
        report.check("API 7：公開した料理が含まれる", len(names) >= 1, str(names))

    res = request(base, "GET", "/me/menus?limit=5", token=token)
    expect(report, "API 16 GET /me/menus", res, 200, ("/me/menus", "get"), no_store=True)
    report.check("API 16：本人のメニュー", [m["menu_id"] for m in res.body.get("menus", [])][:1] == [menu["menu_id"]])
    res = request(base, "GET", f"/me/menus/{menu['menu_id']}?allergen_ids=4,1", token=token)
    expect(report, "API 17 GET /me/menus/{id}", res, 200, ("/me/menus/{menu_id}", "get"), no_store=True)
    report.check("API 17：確認1件", len(res.body.get("confirmations", [])) == 1)
    expect(report, "API 17：存在しないメニュー", request(base, "GET", f"/me/menus/{uuid.uuid4()}", token=token), 404, code="not_found")
    return created


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--allow-writes", action="store_true", help="登録・解析・確認・本人設定を実際に保存する")
    parser.add_argument("--image", type=Path, help="解析に使うJPEG（省略時は英語のメニュー画像を描く）")
    args = parser.parse_args()

    report = Report()
    print(f"接続先：{args.base_url}（{'書き込みあり' if args.allow_writes else '書き込みなし'}）")
    place_id = run_read_only(args.base_url, report)
    created = {}
    if args.allow_writes:
        image = args.image.read_bytes() if args.image else menu_image()
        created = run_writes(args.base_url, report, place_id, image)
    print(f"\n成功 {len(report.passed)}件・失敗 {len(report.failed)}件")
    for line in report.failed:
        print("  失敗：" + line)
    if created:
        print("作成したデータ（後片付け用）：" + json.dumps(created, ensure_ascii=False))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
