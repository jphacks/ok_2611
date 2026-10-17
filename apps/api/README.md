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
| `SUPABASE_URL` / `SUPABASE_SECRET_KEY` | サーバー用の接続情報。RLSを迂回するため、権限はAPIで検証する |
| `GEMINI_API_KEY` | Gemini API |
| `GOOGLE_MAPS_SERVER_API_KEY` | Places API（New）。Places APIだけに制限する |
| `ALLOWED_ORIGINS` | CORSで許可するフロントのURL |
| `AI_PRIOR_WEIGHT_EXPLICIT` / `AI_PRIOR_WEIGHT_POSSIBLE` / `STORE_ANSWER_HALF_LIFE_DAYS` | 予測の設定（仮設定） |
| `AUTH_JWT_SECRET` / `ACCOUNT_TOKEN_TTL_HOURS` | アカウント用トークン（P1） |

## DBエラーの変換

Supabaseクライアント経由のRPC・テーブル操作のエラーは、PostgRESTが付けたHTTPステータスで判定しない。PostgRESTのステータスは [API仕様](../../docs/api.md#エラー) と一致しない（ローカル環境で、存在しないメニューの `P0002` が500で返ることを確認済み）。レスポンス本文の `code`（SQLSTATE）と `message` で判定し、APIのステータスとエラーコードへ変換する。

| `code`（SQLSTATE） | DBの `message` | APIの応答 |
|---|---|---|
| `28000` | `invalid_analysis_token` | 401 `invalid_analysis_token` |
| `P0002` | `menu_not_found`、`account_not_found`（P1） | 404 `not_found` |
| `P0003` | `analysis_expired` | 410 `analysis_expired` |
| `40001` | `request_id_conflict` | 409 `request_id_conflict` |
| `22023` | `answers_invalid`、`dish_not_in_menu`、`confirmation_limit_reached`、`invalid_allergen_ids`、`invalid_dietary_restriction_ids`、`validation_error` | 422。`code` はDBの `message` をそのまま使う |
| `23505` | `accounts.email` の一意制約違反（P1） | 409 `email_already_registered` |
| 上記以外 | その他の制約違反など | 内容に応じて422か409。想定外は500 |

- `22023` で表にない `message`（例：トリガーの `restaurant_mismatch`・`dish_version_mismatch`、解析保存の `dishes_invalid`・`invalid_analysis_token_hash`）は422 `validation_error` にする。これらはAPI側の入力検証で先に防ぐべきものなので、発生しないことをテストで確認する。
- クライアントへはAPI仕様の形式（`{"error": {"code", "message"}}`）で返す。SQLの `message`・`details`・`hint` やPostgRESTの本文をそのまま返さない。ログにもトークン・画像パスなどを含めない。
- `complete_confirmation_session` の成功時は、`replayed=false` を201、`replayed=true` を200で返す。RPCの戻り値に `is_public` は含まれないため、`menus.user_publish_consent`・`restaurant_id` と今回の `publish_consent` から算出する。
- 各RPCの引数・戻り値・SQLSTATEの一覧は [Supabase README](../../supabase/README.md#rpcの契約p0) を参照する。

## コマンド

このディレクトリで実行する。

| コマンド | 用途 |
|---|---|
| `python -m uvicorn app.main:app --reload` | 開発サーバー |
| `python -m pytest` | テスト |
