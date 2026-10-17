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

## コマンド

このディレクトリで実行する。

| コマンド | 用途 |
|---|---|
| `python -m uvicorn app.main:app --reload` | 開発サーバー |
| `python -m pytest` | テスト |
