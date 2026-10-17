# apps/api

Meelyze+ のAPIサーバー。FastAPIで `/api/v1` を提供し、Supabase（PostgreSQL・Storage）、Gemini、Google Places APIを操作する。ブラウザから呼ばれる唯一のサーバーで、秘密鍵と権限の検証はすべてここに置く。

> アプリ本体は未作成。以下は実装方針であり、記載のコマンドや動作は確認していない。

## 技術スタック

| 用途 | 技術 | 備考 |
|---|---|---|
| 言語 | Python | Vercelが対応するバージョンから選び、固定する |
| Webフレームワーク | FastAPI | `/api/v1`、OpenAPIの自動出力 |
| ASGIサーバー（開発） | Uvicorn | 本番はVercel Functions |
| 入出力の型 | Pydantic v2 | 未定義フィールドを拒否（`extra="forbid"`） |
| 設定 | pydantic-settings | `.env` を明示的に読む |
| 画像の受信 | python-multipart | `POST /menus/analyze` |
| 画像の検証 | Pillow | 実際の形式・画素数、EXIFの向き、メタデータ除去 |
| DB・Storage | Supabase Python クライアント | サーバー用鍵（`SUPABASE_SECRET_KEY`）で操作。保存はRPCを使う |
| VLM | Google GenAI SDK（Gemini `gemini-3.8-flash`） | 構造化JSONで出力させ、JSON Schemaで再検証 |
| 店舗検索 | Google Places API（New）、HTTPクライアント（httpx） | Nearby Search、Place Details（IDのみ）。サーバー用キー |
| パスワード（P1） | argon2-cffi | Argon2id |
| アカウント用トークン（P1） | PyJWT | HS256 |
| メールの検証（P1） | email-validator | Pydanticの `EmailStr` |
| テスト | pytest、FastAPIのTestClient | Google・Geminiはモックに置き換える |
| デプロイ | Vercel | Root Directoryは `apps/api` |

- 依存は、実際に動作を確認したバージョンをロックファイルに固定する。資料だけの段階では固定しない。
- レート制限は、Vercelの複数インスタンスで共有できる保存先を使う。保存先は未選定。

仕様・優先度・検証項目は [開発・検証](../../docs/development.md) から参照する。

## 作成するディレクトリ

| パス | 内容 |
|---|---|
| `app/main.py` | FastAPI本体、CORS、ルーター登録 |
| `app/routers/` | エンドポイント |
| `app/schemas/` | Pydanticの入出力 |
| `app/services/` | AI、Storage、`places.py`（Google）、トークン、公開判定、`auth.py`（P1）、`assessment.py`（予測） |
| `tests/` | 解析用トークン、店員確認、公開条件、予測、アカウントのテスト |
| `.env.example` | 環境変数の例（秘密値は空欄） |

実行時に、リポジトリ直下の `apps/api/prompts/menu_analysis.md` と `apps/api/contracts/menu_analysis.schema.json` を使う設計だが、どちらも未作成。実装前に [未作成ファイルの方針](../../docs/development.md#未作成のファイル) に従って作成する。Vercelのデプロイに含まれるかを確認する（[docs/development.md](../../docs/development.md)）。

## 環境変数

`.env.example` を `.env` にコピーする。`.env` はコミットしない。初期値は [開発・検証](../../docs/development.md) を参照する。

| 名前 | 内容 |
|---|---|
| `SUPABASE_URL` | プロジェクトのURL `https://<project-ref>.supabase.co`。**`/rest/v1/` などのパスを付けない**（SDKがパスを付ける）。ローカルは `supabase status` の `API_URL`（`http://127.0.0.1:54321`） |
| `SUPABASE_SECRET_KEY` | サーバー用の鍵（`sb_secret_` で始まる。Dashboard → Project Settings → API Keys → Secret keys）。RLSを迂回するため、権限はAPIで検証する。ローカルは `supabase status` の `SECRET_KEY` |
| `GEMINI_API_KEY` | Gemini API |
| `GOOGLE_MAPS_SERVER_API_KEY` | Places API（New）。Places APIだけに制限する |
| `ALLOWED_ORIGINS` | CORSで許可するフロントのURL |
| `AI_PRIOR_WEIGHT_EXPLICIT` / `AI_PRIOR_WEIGHT_POSSIBLE` / `STORE_ANSWER_HALF_LIFE_DAYS` | 予測の設定（仮設定） |
| `AUTH_JWT_SECRET` / `ACCOUNT_TOKEN_TTL_HOURS` | アカウント用トークン（P1） |

- 公開用キー（`sb_publishable_`）はAPIでもフロントでも使わない。ブラウザはSupabaseに直接アクセスしない。
- `SUPABASE_SECRET_KEY` をフロント（`EXPO_PUBLIC_` の変数）・ログ・レスポンスに含めない。
- Supabaseのプロジェクト `Meelyze-plus` は本番兼用。開発・テストはローカルのSupabase（`supabase start`。手順は [Supabase README](../../supabase/README.md#開発環境の準備)）に向け、本番兼用のプロジェクトへテストデータを書き込まない。

## Supabaseの利用

DB・Storageは Supabase Python クライアント（supabase-py）で、サーバー用鍵を使って操作する。下記の呼び出し方・戻り値は `supabase/tests/integration.py`（supabase-py 2.33.0、ローカル）と `supabase/tests/remote_readonly.py`（`Meelyze-plus`、読取専用）で確認した。APIで使うバージョンは動作確認のうえ別途ロックする。

```python
from supabase import create_client
from postgrest.exceptions import APIError

client = create_client(settings.supabase_url, settings.supabase_secret_key)
```

### APIごとのDB操作

保存はRPCで行い、確認・本人設定の保存を複数の呼び出しに分けない。

| API | 操作 |
|---|---|
| 2 `GET /allergens` | `allergens` を `display_order` 順に取得 |
| 13 `GET /dietary-restrictions` | `dietary_restrictions` を `id` 順に取得 |
| 4 `POST /menus/analyze` | 店舗があれば `restaurants` を `google_place_id` で取得し、なければ追加（同時追加の `23505` は再取得）→ Storageへ画像を保存 → `save_menu_analysis` → 失敗したら画像を削除 → 予測用の過去回答を取得 |
| 5 `GET /menus/{menu_id}` | `menus` を `id` で取得し、解析用トークンのSHA-256と `analysis_token_hash` を `hmac.compare_digest` で比較、`analysis_expires_at` で期限を判定。料理は `position` 順 |
| 6 `POST /menus/{menu_id}/confirmations` | `complete_confirmation_session` を1回だけ呼ぶ。`is_public` は `menus.user_publish_consent`・`restaurant_id` と今回の `publish_consent` から算出 |
| 7 `GET /places/{id}/public-menus` | 公開ビュー3つだけを使う |
| 8 `POST /auth/register` | `accounts` に5列だけを追加（下記）。`23505` は409 |
| 9 `POST /auth/login` | `accounts` を `email`（正規化後）で取得。再ハッシュ時は `password_hash`・`updated_at` だけを更新 |
| 10 `GET /me` | `accounts` から `password_hash` 以外を取得 |
| 11・14 `GET /me/...` | `account_allergens`・`account_dietary_restrictions` を `account_id = sub` で昇順に取得 |
| 12・15 `PUT /me/...` | `replace_account_allergens`・`replace_account_dietary_restrictions` |
| 16・17 `GET /me/menus...` | 基礎テーブルを常に `account_id = sub` で絞る（下記） |

### RPCの呼び出しと戻り値

```python
# 解析保存 → menu_id（str）。ゲストは p_account_id を省略する
menu_id = client.rpc("save_menu_analysis", {
    "p_restaurant_id": restaurant_id,          # 店舗未選択は None
    "p_image_path": image_path,                # Storageに保存したパス
    "p_analysis_token_hash": token_sha256_hex,  # 小文字16進64文字。生トークンは渡さない
    "p_dishes": dishes,                        # [{name, name_key, translations, price, currency, ai_result}]
    "p_ai_model": ai_model,
    "p_prompt_version": "v4",
    "p_account_id": account_id,                # 検証済みJWTの sub。本文の値は使わない
}).execute().data

# 店員確認 → {"session_id", "confirmed_at", "replayed"}（dict 1件）
result = client.rpc("complete_confirmation_session", {
    "p_menu_id": menu_id,
    "p_analysis_token_hash": token_sha256_hex,
    "p_request_id": request_id,
    "p_answers": [{"dish_id": ..., "allergen_id": 4, "answer": "contains"}],
    "p_dietary_answers": [{"dish_id": ..., "dietary_restriction_id": 1, "answer": "unknown"}],
    "p_publish_consent": publish_consent,
}).execute().data

# 本人設定の全件置換 → 置き換え後のIDの昇順リスト（[] で全解除）
ids = client.rpc("replace_account_allergens", {"p_account_id": sub, "p_allergen_ids": [6, 4]}).execute().data
ids = client.rpc("replace_account_dietary_restrictions",
                 {"p_account_id": sub, "p_dietary_restriction_ids": [4, 1]}).execute().data
```

- 回答に `dish_version` は送らない（DBが保存する）。`answers`・`dietary_answers` は欠落・nullを送らず、対象がない側は空配列にする。
- 解析保存の `p_dishes` に未定義のキーを含めると `22023` `dishes_invalid` になる。VLMの出力はJSON Schemaで検証してから渡す。

### アカウント（P1）

```python
account = client.table("accounts").insert({
    "email": normalized_email,          # 前後空白を除き小文字化済み（DBは検査だけ）
    "nickname": nickname.strip(),
    "password_hash": argon2id_hash,     # $argon2id$ で始まるPHC形式
    "publish_consent": publish_consent, # 明示的な true／false
    "publish_consent_version": "2026-10-17-v1",
}).execute().data[0]
```

- `id`・`publish_consent_recorded_at`・`created_at`・`updated_at` はDBが決める。指定すると権限エラー（`42501`）になる。
- 更新できるのは再ハッシュ時の `password_hash`・`updated_at` だけ。メール・ニックネーム・同意は更新できず、アカウントの削除もできない。

### 本人履歴と予測用の取得

- 本人履歴（API 16・17）は、どのクエリにも `account_id = sub` を付ける。店舗・カーソルの条件はANDで追加する。並び順は `created_at DESC, id DESC`。条件とSQL例は [Supabase README「本人履歴の取得」](../../supabase/README.md#本人履歴の取得api-1617)。
- 詳細（API 17）は `id = menu_id` と `account_id = sub` を同じクエリで指定し、0件なら404（他人・ゲスト・存在しないIDを区別しない）。関連する料理・確認はリソース埋め込みで取得できる（例：`select("id,dishes(*),confirmation_sessions(*,confirmation_answers(*),confirmation_dietary_answers(*))")` に `.eq("id", menu_id).eq("account_id", sub)`）。
- 予測（API 4・5・17）は、同じ店舗・`name_key`・項目IDの全回答（非公開を含む）を使う。店舗未選択の回答は使わない。SQL例は [Supabase README「予測用の過去回答の取得」](../../supabase/README.md#予測用の過去回答の取得api-4517)。
- 公開集計（API 7）は公開ビューだけを使い、本人履歴・予測用の取得と混ぜない。
- SDKのクエリビルダーで組んだ条件（特にカーソルの `or` 条件）は未検証のため、APIのテストで所有者条件が外れないことを確認する。

### Storage

```python
bucket = client.storage.from_("menu-images")
bucket.upload(image_path, image_bytes, {"content-type": "image/jpeg"})  # 実際の形式に合わせる
bucket.remove([image_path])                                            # DB登録失敗時・期限後の削除
```

- バケットは非公開・2,097,152バイト・JPEG／PNGのみ。バケットでも拒否されるが、APIは保存前に検証して413・415を返す。
- 画像のパスはランダムに作り（`menus.image_path` は一意）、パス・URL・署名付きURLをクライアントへ返さない。
- 削除はStorage APIで行う（`storage.objects` を直接DELETEしない）。画像を削除してもメニュー・料理・回答・本人履歴は残る。

### テスト

- APIのテストはローカルのSupabaseに対して行う。`supabase start` で起動し、`supabase status` の `API_URL`・`SECRET_KEY` を使う。本番兼用の `Meelyze-plus` に書き込むテストは行わない。
- ローカルのDBを初期化する場合は `supabase db reset`（マスタはマイグレーションで再投入される）。

## DBエラーの変換

Supabaseクライアント経由のRPC・テーブル操作のエラーは、PostgRESTが付けたHTTPステータスで判定しない。PostgRESTのステータスは [API仕様](../../docs/api.md#エラー) と一致しない（確認済みの例：`P0002` は500、`22023` は400、`42501` は401／403）。supabase-py では `postgrest.exceptions.APIError` の `code`（SQLSTATE）と `message` で判定し、APIのステータスとエラーコードへ変換する。

| `code`（SQLSTATE） | DBの `message` | APIの応答 |
|---|---|---|
| `28000` | `invalid_analysis_token` | 401 `invalid_analysis_token` |
| `P0002` | `menu_not_found` | 404 `not_found` |
| `P0002` | `account_not_found`（P1。解析保存・本人設定の置換） | 401 `unauthorized`（トークンの `sub` のアカウントがない。トークン検証の失敗と同じ扱い） |
| `P0003` | `analysis_expired` | 410 `analysis_expired` |
| `40001` | `request_id_conflict` | 409 `request_id_conflict` |
| `22023` | `answers_invalid`、`dish_not_in_menu`、`confirmation_limit_reached`、`invalid_allergen_ids`、`invalid_dietary_restriction_ids`、`validation_error` | 422。`code` はDBの `message` をそのまま使う |
| `23505` | `accounts.email` の一意制約違反（P1） | 409 `email_already_registered` |
| `42501` | 権限エラー | 500（APIは `service_role` の権限内でだけ操作するため、発生したら実装の誤り） |
| `55000` | `snapshot_is_immutable` | 500（APIは保存済みの行を更新しないため、発生したら実装の誤り） |
| 上記以外 | その他の制約違反など | 内容に応じて422か409。想定外は500 |

- `22023` で表にない `message`（例：トリガーの `restaurant_mismatch`・`dish_version_mismatch`、解析保存の `dishes_invalid`・`invalid_analysis_token_hash`）は422 `validation_error` にする。これらはAPI側の入力検証で先に防ぐべきものなので、発生しないことをテストで確認する。
- クライアントへはAPI仕様の形式（`{"error": {"code", "message"}}`）で返す。SQLの `message`・`details`・`hint` やPostgRESTの本文をそのまま返さない。ログにもトークン・画像パスなどを含めない。
- `complete_confirmation_session` の成功時は、`replayed=false` を201、`replayed=true` を200で返す。RPCの戻り値に `is_public` は含まれないため、`menus.user_publish_consent`・`restaurant_id` と今回の `publish_consent` から算出する。
- 各RPCの引数・戻り値・SQLSTATEの一覧は [Supabase README](../../supabase/README.md#rpcの契約) と [DB仕様](../../docs/database.md#db関数rpc) を参照する。

## コマンド

このディレクトリで実行する。

| コマンド | 用途 |
|---|---|
| `python -m uvicorn app.main:app --reload` | 開発サーバー |
| `python -m pytest` | テスト |
