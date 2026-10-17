# Supabaseのセットアップ

構造と制約の正本は [DB仕様](../docs/database.md)、検証項目は [開発・検証](../docs/development.md#検証) を参照する。本書は配置、開発環境の準備、実行手順、検証結果、API側への引継ぎをまとめる。

状態（2026-10-17）：P0の3マイグレーションと検証SQLを作成し、**ローカル開発環境でのみ**適用・検証した。クラウドの開発プロジェクトへのリンク・適用、並行実行・SDK・実Storage操作の検証は [03](task/03_verify_apply.md)、アカウント関連は [02](task/02_accounts_history.md) で行う。

## 構成

```
supabase/
├── config.toml      # ローカル開発環境の設定（秘密値なし）
├── migrations/      # SQL・DB変更履歴。ファイル名順に適用する
├── tests/verify.sql # 開発DB用の検証SQL（マイグレーションではない。最後にROLLBACK）
├── package.json     # Supabase CLI（npm）のバージョン固定。package-lock.json でロック
├── task/            # 作業タスク
└── README.md        # このファイル
```

| ファイル | 内容 | 状態 |
|---|---|---|
| `migrations/20261016000000_init_schema.sql` | 確認用8テーブル（食事制限のマスタ・回答を含む）、索引、トリガー、`save_menu_analysis`（P0版）・`complete_confirmation_session`、公開ビュー3つ、RLS・権限 | 作成・ローカル検証済み |
| `migrations/20261016000100_seed_master_data.sql` | アレルゲン29種・食事制限4種 | 作成・ローカル検証済み |
| `migrations/20261016000200_storage.sql` | 非公開バケット `menu-images` と既存設定の検査 | 作成・ローカル検証済み |
| `migrations/20261017000000_accounts.sql` | 登録時公開同意を含むアカウント3テーブル、本人設定の置換RPC2つ、RLS・権限（P1） | 未作成（02） |
| `migrations/20261017000100_publication_history.sql` | `menus.account_id` のFK・履歴索引・ゲストの同意false制約、`save_menu_analysis` の所有者引数追加と登録時同意のコピー（P1） | 未作成（02） |
| `tests/verify.sql` | 開発DB用の検証。最後にロールバックする | P0分のみ |

## 開発環境の準備

必要なもの：Docker互換のコンテナ実行環境（Docker Desktopなど）、Node.js（npm）。

Supabase CLIは [公式手順](https://supabase.com/docs/guides/local-development/cli/getting-started) のnpm方式で `supabase/` に固定している（Homebrew方式はこの端末ではXcode Command Line Toolsの不足で失敗したため）。グローバル導入した `supabase` でも同じバージョンなら同様に使える。

```sh
# リポジトリ直下で実行する
npm ci --prefix supabase                 # CLI 2.121.0 をロックファイルどおり導入
alias sb="$PWD/supabase/node_modules/.bin/supabase"

sb start                                 # ローカルのDB・Storage等を起動し、migrations/ を順に適用
sb status                                # 接続先・ローカル用キーの表示
sb db reset                              # ローカルDBを空にして migrations/ を再適用
sb stop                                  # 停止
```

- `config.toml` は `supabase init` の生成値から `project_id` と `[db.seed] enabled = false` だけを変更した。必須マスタはマイグレーションに含め、`seed.sql` は使わない。
- ローカルの `sb status` が表示するキーはローカル専用の既定値。クラウドの秘密値はこのリポジトリに置かない（[00](task/00_user_setup.md)）。
- 以後のSQLはマイグレーション経由で管理し、同じ環境でSQL Editorからの手動適用と混在させない。

## 適用手順（クラウド）

[03](task/03_verify_apply.md) で行う。リポジトリ直下で対象プロジェクトにリンクしてから適用する。

```sh
sb link --project-ref <project-ref>
sb db push
```

- 同じ環境で、SQL Editorからの手動実行と `db push` を混在させない。適用履歴が食い違う。
- 適用済みのマイグレーションは編集しない。変更は新しいタイムスタンプ（UTC、`YYYYMMDDHHMMSS_内容.sql`）のファイルで追加する。
- 初回マイグレーションは新しい環境専用である。同名のテーブルがあると失敗し、旧DDLからの上書き移行には使えない。
- 必須マスタはマイグレーションに含め、環境間で同じIDと値を適用する。`seed.sql` も `db push --include-seed` でリモート適用できるが、本プロジェクトの必須マスタには使わない。[Supabaseの適用手順](https://supabase.com/docs/guides/deployment/database-migrations)
- 本番環境で実行する前、または既存のテーブルを削除する前には、対象の環境と変更内容を確認する。
- ローカルの `db` は PostgreSQL 17（`config.toml` の `major_version = 17`）。クラウド側のバージョンはリンク時に確認する。

## 検証の実行

```sh
# ローカルDBで実行（psql はDBコンテナ内のものを使う）
docker exec -i supabase_db_meelyze-plus psql -U postgres -d postgres -X < supabase/tests/verify.sql

# 失敗を検出できることの確認（最後に意図的に失敗させる）
docker exec -i supabase_db_meelyze-plus psql -U postgres -d postgres -X -v inject_failure=1 < supabase/tests/verify.sql
```

- 全体を1トランザクションで実行し、最後に `ROLLBACK` する。期待と異なる結果・想定外の例外は `ON_ERROR_STOP` により終了コード3で停止し、何もコミットされない。
- 成功時は `verify.sql: all checks passed (rolling back)` を表示して終了コード0。
- `anon`・`authenticated`・`service_role` は `SET LOCAL ROLE` で切り替えて操作する（ローカルの `postgres` はこれらのロールのメンバー）。
- 期限切れのメニュー・確認はRPCで作れない（作成日時をクライアント申告で決めない）ため、管理者接続で過去日時の行を直接作って検証する。

### 検証項目

| 区分 | 内容 |
|---|---|
| 構造 | 8テーブルの列・型・NULL、RLS有効・ポリシーなし、一意制約・外部キー（`menus.restaurant_id` は削除制限）、索引7つ、トリガー8つ、RPC2つ（各1シグネチャ・security invoker）、公開ビュー3つの列・`security_invoker=true`、ビューに画像パス・トークンハッシュ・所有者がないこと |
| マスタ | アレルゲン29件（required 9／recommended 20、ID 1〜10のcode維持、表示順1〜29）、食事制限4件を正本と双方向で一致 |
| 権限 | `PUBLIC`・`anon`・`authenticated` にテーブル・ビュー・列・シーケンス・関数の権限がないこと。`service_role` の権限が正本の表と一致（列権限は `UPDATE(menus.id)` のみ、実行はRPC2つのみ）。`anon`・`authenticated` の読取・書込・削除・RPC実行が `42501` で拒否されること |
| 解析保存 | 3料理の配列順の `position`、`currency` 既定 `JPY`、`price` のNULL、利用者同意false、期限＝作成＋24時間。ゲスト（店舗なし）、20料理。0／21料理、配列以外、未定義キー、必須キー欠落、型違い、不正ハッシュ（大文字・63文字・null）、2件目の料理の制約違反、存在しない店舗、画像パス・ハッシュの重複、過去の期限を拒否し、メニューが残らないこと |
| 確認保存 | アレルゲンのみ／食事制限のみ／両方、`unknown`・店員不同意の保持、確認の店舗はメニューから決定、`dish_version` 保存。50回答・10料理ちょうどは成功 |
| 確認の拒否 | 両方空、null・配列以外、`request_id`・店員同意のnull、51回答（片側・合計）、11料理、未知ID（アレルゲン30・0、食事制限5）、回答語彙の取り違え、重複、直積不足（両配列）、料理集合の不一致、別メニュー・存在しない料理（`dish_not_in_menu`）、キー欠落・null・不正値・未定義フィールド・型違い。拒否後に確認・回答が増えていないこと |
| トークン・期限 | 他メニューのトークン・大文字・生トークン・nullは `28000`、存在しないメニューは `P0002`、期限切れは新規・再送とも `P0003` |
| 再送・上限 | 並び替え・大文字UUIDの再送は同じ `session_id`・`confirmed_at` で `replayed=true`、行は増えない。内容・店員同意・片側の欠落の変更は `40001`。5件到達後も既存の再送は成功し、新規6件目は `confirmation_limit_reached`、6件目への別内容は `40001` |
| トリガー | RPCを経由しない挿入でも上限・店舗一致・料理の所属・版の不一致（両回答表）を拒否 |
| 不変性 | `service_role` の `FOR UPDATE` は成功し、`UPDATE menus SET id = id` は `snapshot_is_immutable`、他列・他表の更新と削除は `42501`。所有者（`postgres`）の更新も5表すべてトリガーで拒否 |
| 公開 | ゲストの確認は店員同意ありでも保存されるが公開ビューに出ない。P0の保存は利用者同意falseのため、検証メニューはどのビューにも出ない |
| Storage | `menu-images` が非公開・2,097,152バイト・JPEG／PNGのみ、バケットを対象にしたポリシーがないこと |

### 実施結果（2026-10-17、ローカル）

| 項目 | 内容 |
|---|---|
| 環境 | macOS（Darwin 25.2.0, arm64）、Docker Desktop（Engine 29.3.1）、Node.js 24.14.1／npm 11.11.0 |
| ツール | Supabase CLI 2.121.0（npm、`package-lock.json` で固定）、PostgreSQL 17.11（ローカルDBイメージ）、storage-api v1.82.1 |
| 適用 | `sb start`・`sb db reset` で空のDBに3マイグレーションを順番に適用できた。`sb migration list --local` で3件とも適用済み |
| 静的検査 | `sb db lint --level warning`：`No schema errors found` |
| `verify.sql` | 全8区分が成功、終了コード0。実行後に全6データテーブルが0行（ロールバックを確認） |
| 失敗の検出 | `-v inject_failure=1`、および一時的な権限付与（`anon` への `SELECT`、`service_role` への `UPDATE(user_publish_consent)`）で、それぞれ該当の検査が失敗し終了コード3になることを確認後、付与を取り消した |
| Storageの停止 | バケットを `public=true`・容量上限変更・MIME追加・MIME null に変えた状態と、バケットを対象にしたポリシーがある状態で、Storageマイグレーションが例外で停止することを、ロールバックするトランザクション内で確認した。設定が一致する場合は何もしない |
| REST経由の確認 | ローカルAPIゲートウェイで、公開用キー（anon）はテーブル・ビュー・RPCとも `42501`（HTTP 401）、サーバー用キーは読取・RPC実行が可能（未知メニューで `P0002`）。anonによる `menu-images` の一覧は `200 []`（ポリシーなしでRLSにより空） |

### 未検証（後続タスク）

- クラウドの開発プロジェクトへのリンク・`db push`・2回目の差分なし確認（03。00の準備が必要）。
- 複数接続からの並行送信（5件上限・同一 `request_id`）、Supabase SDK経由のRPCの引数名・戻り値・エラー、実Storageのアップロード・取得・削除と匿名取得の拒否、容量・MIME制限の実動作（03）。
- 利用者同意trueを含む公開条件の8通り、アカウント・所有者・履歴（02）。P0の通常保存では同意trueのメニューは作られないため、公開行が出る条件は未検証。

## RPCの契約（P0）

どちらも `security invoker`、`service_role` だけが実行できる。

### `save_menu_analysis(p_restaurant_id, p_image_path, p_analysis_token_hash, p_dishes, p_ai_model, p_prompt_version, p_analysis_expires_at default null) → uuid`

- メニュー1件と料理1〜20件を1トランザクションで登録し、`menu_id` を返す。利用者同意は常にfalse（P0版は所有者引数なし）。
- `p_dishes` の各要素は `name`・`name_key`（文字列）、`translations`・`ai_result`（オブジェクト）、`price`（数値かnull、省略可）、`currency`（文字列かnull、省略時 `JPY`）だけを持つ。配列順が `position`（1始まり）になる。
- `p_analysis_token_hash` は小文字16進64文字。`p_analysis_expires_at` 省略時は `now() + 24時間`。
- エラー：`22023`（`dishes_invalid`、`invalid_analysis_token_hash`）。料理名の長さ・負の価格・過去の期限などの制約違反は `23514`、存在しない店舗は `23503`、画像パス・ハッシュの重複は `23505` をそのまま返す。
- 02の `20261017000100` でこの7引数版を `drop function public.save_menu_analysis(uuid, text, text, jsonb, text, text, timestamptz)` で削除し、末尾に `p_account_id uuid default null` を加えた定義に置き換える。

### `complete_confirmation_session(p_menu_id, p_analysis_token_hash, p_request_id, p_answers, p_dietary_answers, p_publish_consent) → (session_id uuid, confirmed_at timestamptz, replayed boolean)`

- 戻り値はOUT引数の1行（PostgRESTでは単一オブジェクト）。
- `p_answers` の要素は `{dish_id, allergen_id, answer}`、`p_dietary_answers` の要素は `{dish_id, dietary_restriction_id, answer}` のちょうど3キー。`dish_version` は送らず、DBが料理の現在の版を保存する。
- 処理順：メニューを `FOR UPDATE` → トークン → 期限 → 入力検証 → 同一 `request_id` の再送判定 → 新規だけ5件上限 → 一括保存。

| SQLSTATE | メッセージ | 条件 |
|---|---|---|
| `P0002` | `menu_not_found` | メニューなし |
| `28000` | `invalid_analysis_token` | ハッシュの形式不正・null・不一致 |
| `P0003` | `analysis_expired` | 期限切れ（再送も含む） |
| `22023` | `validation_error` | `p_request_id`・`p_publish_consent` がnull |
| `22023` | `answers_invalid` | 配列以外・null、合計0／51以上、要素の形式・値、重複、未知ID、料理の和集合0／11以上、直積不足、両配列の料理集合不一致 |
| `22023` | `dish_not_in_menu` | 料理がこのメニューにない |
| `40001` | `request_id_conflict` | 同じ `request_id` で内容・店員同意が異なる |
| `22023` | `confirmation_limit_reached` | 新規の6件目 |

トリガーが直接の挿入に対して返すエラー：`22023`（`restaurant_mismatch`、`dish_version_mismatch`、`dish_not_in_menu`、`confirmation_limit_reached`）、更新は `55000`（`snapshot_is_immutable`）。

## API側への引継ぎ

- SQLSTATEからHTTPへの変換はFastAPIで行う。PostgRESTのHTTPステータスはAPI仕様と一致しない（例：`P0002` は500で返る）ため、レスポンス本文の `code`・`message` で判定する。変換表は [API README](../apps/api/README.md#dbエラーの変換) に記載した。
- `is_public` はRPCの戻り値に含まれない。`menus.user_publish_consent`・`restaurant_id` と今回の `publish_consent` からAPIで算出する。
- 画像の画素数・実形式の検証、VLM JSONの詳細検証（`contracts/menu_analysis.schema.json`）、`name_key` の生成、予測計算、解析トークンの生成とSHA-256化はAPIの担当。
- Storage保存後に `save_menu_analysis` が失敗した場合は、APIがStorage APIで画像を削除する。
- 公開APIの集計・返却項目の制限（`menu_id`・`session_id`・個別回答を返さない）はAPIの担当。ビューは結合用IDを含む。

## 画像の削除（開発中の手動手順）

画像は原則24時間で削除する。開発中は手動で削除し、一般公開前に定期削除を実装する（未決事項）。`storage.objects` を直接DELETEせず、サーバー用鍵でStorage APIを使う。

1. 対象を特定する：`select image_path from public.menus where created_at < now() - interval '24 hours';`（管理者接続またはサーバー用鍵）
2. Storage APIで削除する（例：supabase-py の `client.storage.from_("menu-images").remove([paths])`、またはDashboardのStorage画面）。
3. メニュー・料理・回答の行は削除しない。`image_path` は削除後も残る。

## 仕様で明記がなく実装で決めた事項

| 事項 | 実装 |
|---|---|
| 更新拒否のSQLSTATE | `55000`（`snapshot_is_immutable`） |
| `save_menu_analysis` の入力エラー | `22023`（`dishes_invalid`、`invalid_analysis_token_hash`）。料理要素の未定義キーも拒否 |
| 確認保存の `request_id`・店員同意のnull | `22023`（`validation_error`） |
| トリガーのエラーメッセージ | `restaurant_mismatch`、`dish_version_mismatch` |
| `dish_version`・`dish.version` | NOT NULL。`version >= 1` |
| 文字列の空チェック | `image_path`・`name_key`・`ai_model`・`prompt_version` は1文字以上、`currency` は大文字3文字 |
