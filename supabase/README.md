# Supabaseのセットアップ

構造と制約の正本は [DB仕様](../docs/database.md)、検証項目は [開発・検証](../docs/development.md#検証) を参照する。本書は配置、開発環境の準備、実行手順、検証結果、API側への引継ぎをまとめる。

状態（2026-10-17）：P0（[01](task/01_p0_database.md)）・P1（[02](task/02_accounts_history.md)）の5マイグレーションと検証SQLを作成し、**ローカル開発環境でのみ**適用・検証した。クラウドの開発プロジェクトへのリンク・適用、並行実行・SDK・実Storage操作の検証は [03](task/03_verify_apply.md) で行う。

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
| `migrations/20261017000000_accounts.sql` | 登録時公開同意を含むアカウント3テーブル、本人設定の置換RPC2つ、RLS・権限（P1） | 作成・ローカル検証済み |
| `migrations/20261017000100_publication_history.sql` | `menus.account_id` のFK・履歴索引・ゲストの同意false制約、`save_menu_analysis` の所有者引数追加と登録時同意のコピー（P1） | 作成・ローカル検証済み |
| `tests/verify.sql` | 開発DB用の検証（P0・P1、12区分）。最後にロールバックする | 作成・ローカル検証済み |

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
| 構造 | 11テーブルの列・型・NULL、RLS有効・ポリシーなし、一意制約（`accounts_email_key` を含む）、外部キー15本と削除動作（`menus` の店舗・所有者は削除制限、本人設定はアカウント削除でカスケード・マスタは削除制限）、本人設定の複合主キー、ゲストの同意false制約、索引8つ（履歴索引 `(account_id, created_at desc, id desc)` を含む）、トリガー8つ、RPC4つ（各1シグネチャ・旧 `save_menu_analysis` なし・security invoker）、公開ビュー3つの列・`security_invoker=true`、ビューに画像パス・トークンハッシュ・所有者がないこと |
| マスタ | アレルゲン29件（required 9／recommended 20、ID 1〜10のcode維持、表示順1〜29）、食事制限4件を正本と双方向で一致 |
| 権限 | `PUBLIC`・`anon`・`authenticated` にテーブル・ビュー・列・シーケンス・関数の権限がないこと。`service_role` の権限が正本の表と一致（列権限は `accounts` の登録用5列のINSERT・`UPDATE(password_hash, updated_at)`・`UPDATE(menus.id)` のみ、実行はRPC4つのみ）。`anon`・`authenticated` の読取・書込・削除・RPC実行（アカウント3表・置換RPCを含む）が `42501` で拒否されること |
| 解析保存 | 3料理の配列順の `position`、`currency` 既定 `JPY`、`price` のNULL、利用者同意false、期限＝作成＋24時間。ゲスト（店舗なし）、20料理。0／21料理、配列以外、未定義キー、必須キー欠落、型違い、不正ハッシュ（大文字・63文字・null）、2件目の料理の制約違反、存在しない店舗、画像パス・ハッシュの重複、過去の期限を拒否し、メニューが残らないこと |
| 確認保存 | アレルゲンのみ／食事制限のみ／両方、`unknown`・店員不同意の保持、確認の店舗はメニューから決定、`dish_version` 保存。50回答・10料理ちょうどは成功 |
| 確認の拒否 | 両方空、null・配列以外、`request_id`・店員同意のnull、51回答（片側・合計）、11料理、未知ID（アレルゲン30・0、食事制限5）、回答語彙の取り違え、重複、直積不足（両配列）、料理集合の不一致、別メニュー・存在しない料理（`dish_not_in_menu`）、キー欠落・null・不正値・未定義フィールド・型違い。拒否後に確認・回答が増えていないこと |
| トークン・期限 | 他メニューのトークン・大文字・生トークン・nullは `28000`、存在しないメニューは `P0002`、期限切れは新規・再送とも `P0003` |
| 再送・上限 | 並び替え・大文字UUIDの再送は同じ `session_id`・`confirmed_at` で `replayed=true`、行は増えない。内容・店員同意・片側の欠落の変更は `40001`。5件到達後も既存の再送は成功し、新規6件目は `confirmation_limit_reached`、6件目への別内容は `40001` |
| トリガー | RPCを経由しない挿入でも上限・店舗一致・料理の所属・版の不一致（両回答表）を拒否 |
| 不変性 | `service_role` の `FOR UPDATE` は成功し、`UPDATE menus SET id = id` は `snapshot_is_immutable`、他列・他表の更新と削除は `42501`。所有者（`postgres`）の更新も5表すべてトリガーで拒否 |
| 公開 | ゲストの確認は店員同意ありでも保存されるが公開ビューに出ない。P0の保存は利用者同意falseのため、検証メニューはどのビューにも出ない |
| Storage | `menu-images` が非公開・2,097,152バイト・JPEG／PNGのみ、バケットを対象にしたポリシーがないこと |
| アカウント | 登録時同意true／falseとも登録でき、記録日時・作成日時はDBの `now()`。メール254文字・ニックネーム30文字は可。正規化済みメールの重複（`23505`）、大文字・前後空白・255文字・2文字のメール、空・前後空白・31文字のニックネーム、argon2i・平文・SHA-256のハッシュ、同意のnull・欠落、文言版の空・欠落を拒否。`id`・日時をAPIから指定すると `42501`。再ハッシュと行ロックは可能、メール・ニックネーム・同意・文言版・日時の更新とアカウント削除は `42501` |
| 本人設定 | 両RPCで昇順の結果・全件置換・空配列での全解除ができ、他アカウントに影響しない。未知・0・負・重複・小数・文字列・null要素・オブジェクト・null配列は `22023`、存在しない・NULLのアカウントは `P0002` で、元の設定が残る。削除後の追加で失敗させても（検証用トリガー）元の設定が残る。本人設定表の直接のselect・insert・deleteは可、UPDATEは `42501`。アカウント削除で本人設定はカスケード、設定済みマスタの削除は `23503` |
| 所有者・同意 | 登録時同意true／falseのアカウントとゲストで解析し、所有者・同意がアカウントからコピーされる。存在しないアカウントは `P0002` でメニューを残さない。所有者なし・同意trueは `23514`。所有者・同意の更新は `service_role` で `42501`、所有者接続でもトリガーで拒否。メニューを持つアカウントの削除は `23503` |
| 公開条件 | 店舗有無×利用者同意×店員同意の8通りで、3つともtrueの確認だけが両回答ビューに出る。同じメニューの非公開確認の回答は出ず、`published_menus` はそのメニューの料理だけで `published_at` は公開確認の日時 |
| 本人履歴 | README「本人履歴の取得」と同じSQLで、本人分だけを新しい順に返す（未確認・非公開・店舗未選択・同意falseの登録者を含む）。`is_public`・確認件数・英語の料理名順。店舗条件・カーソルでのページング（重複・欠落なし）・他人のメニューを指すカーソル・未来のカーソルでも本人分だけ。存在しない・NULLの所有者は0件。詳細は `menu_id` と所有者を同じ条件で検証し、他人・ゲスト・存在しないIDは0件。確認一覧も当該メニュー・本人分だけ |

### 実施結果（2026-10-17、ローカル）

| 項目 | 内容 |
|---|---|
| 環境 | macOS（Darwin 25.2.0, arm64）、Docker Desktop（Engine 29.3.1）、Node.js 24.14.1／npm 11.11.0 |
| ツール | Supabase CLI 2.121.0（npm、`package-lock.json` で固定）、PostgreSQL 17.11（ローカルDBイメージ）、storage-api v1.82.1 |
| 適用（空のDB） | `sb db reset` で空のDBに5マイグレーションを順番に適用できた。`sb migration list --local` で5件とも適用済み |
| 適用（P0から追加） | `sb db reset --version 20261016000200` でP0だけを適用し、P0のRPCでゲストの解析・店員同意ありの確認をコミットした後、`sb migration up --local` でP1の2件を追加適用できた。既存メニューは所有者NULL・同意falseのまま、公開行0件。この状態でも `verify.sql` が成功 |
| 静的検査 | `sb db lint --level warning`：`No schema errors found` |
| `verify.sql` | 全12区分が成功、終了コード0。実行後にデータテーブル（アカウント3表を含む）が0行（ロールバックを確認） |
| 失敗の検出 | `-v inject_failure=1`、一時的な権限付与（`anon` への `SELECT`、`service_role` への `UPDATE(user_publish_consent)`・`UPDATE(accounts.publish_consent)`）、利用者同意の条件を外した公開回答ビューへの差し替えで、それぞれ検査が失敗し終了コード3になることを確認した。変更は取り消し、または `sb db reset` で戻した |
| Storageの停止 | バケットを `public=true`・容量上限変更・MIME追加・MIME null に変えた状態と、バケットを対象にしたポリシーがある状態で、Storageマイグレーションが例外で停止することを、ロールバックするトランザクション内で確認した。設定が一致する場合は何もしない |
| REST経由の確認 | ローカルAPIゲートウェイで、公開用キー（anon）はテーブル・ビュー・RPC（置換RPC・`accounts` を含む）とも `42501`（HTTP 401）、サーバー用キーは読取・RPC実行が可能（未知メニューで `P0002`）。サーバー用キーで `accounts` を登録でき、`publish_consent_recorded_at` を指定すると `42501`（HTTP 403）。置換RPCはJSON配列の引数を受け取り、昇順の配列を返す（未知IDは `22023`、HTTP 400）。anonによる `menu-images` の一覧は `200 []`（ポリシーなしでRLSにより空） |

### 未検証（後続タスク）

- クラウドの開発プロジェクトへのリンク・`db push`・2回目の差分なし確認（03。00の準備が必要）。
- 複数接続からの並行送信（5件上限・同一 `request_id`）、本人設定への同時置換、Supabase SDK経由のRPC4つの引数名・戻り値・エラー、実Storageのアップロード・取得・削除と匿名取得の拒否、容量・MIME制限の実動作、画像削除・トークン失効後の履歴閲覧（03）。
- JWTの署名・期限・本人確認、メール正規化・パスワード照合、所有者条件をAPIが常に付けること、公開APIの集計・返却項目の制限はAPI実装の担当で、DBの検証では確認していない。

## RPCの契約

4つとも `security invoker`、`service_role` だけが実行できる。引数・戻り値はPostgREST（Supabase SDKの `rpc`）からJSONで渡す。

### `save_menu_analysis(p_restaurant_id, p_image_path, p_analysis_token_hash, p_dishes, p_ai_model, p_prompt_version, p_analysis_expires_at default null, p_account_id default null) → uuid`

- メニュー1件と料理1〜20件を1トランザクションで登録し、`menu_id` を返す。
- `p_account_id` はAPIが検証済みアカウントJWTの `sub` から渡す（ゲストは省略・NULL）。アカウントがあれば所有者にし、`accounts.publish_consent` を `menus.user_publish_consent` にコピーする。ゲストは所有者NULL・同意false。利用者同意のbooleanは引数にない。
- `p_dishes` の各要素は `name`・`name_key`（文字列）、`translations`・`ai_result`（オブジェクト）、`price`（数値かnull、省略可）、`currency`（文字列かnull、省略時 `JPY`）だけを持つ。配列順が `position`（1始まり）になる。
- `p_analysis_token_hash` は小文字16進64文字。`p_analysis_expires_at` 省略時は `now() + 24時間`。
- エラー：`P0002`（`account_not_found`）、`22023`（`dishes_invalid`、`invalid_analysis_token_hash`）。料理名の長さ・負の価格・過去の期限などの制約違反は `23514`、存在しない店舗は `23503`、画像パス・ハッシュの重複は `23505` をそのまま返す。
- P0の7引数版は `20261017000100` で削除済み。引数違いの旧関数は残っていない。

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

### `replace_account_allergens(p_account_id, p_allergen_ids) → smallint[]`・`replace_account_dietary_restrictions(p_account_id, p_dietary_restriction_ids) → smallint[]`

- `p_account_id` はAPIがアカウント用トークンの `sub` から渡す。IDの配列はJSON配列（`jsonb`）で渡す。
- アカウント行を `FOR UPDATE` でロックし、検証後に既存の行を削除して追加する。置き換え後のIDを昇順の配列で返す。空配列は全解除。
- 途中で失敗した場合は元の設定が残る。アレルゲンと食事制限は別RPC（別トランザクション）。

| SQLSTATE | メッセージ | 条件 |
|---|---|---|
| `P0002` | `account_not_found` | アカウントなし・NULL |
| `22023` | `invalid_allergen_ids`／`invalid_dietary_restriction_ids` | 配列以外・null、整数以外の要素、重複、未知のID |

## アカウントの登録・更新（テーブル直接）

登録・ログイン用のRPCはない。APIは `service_role` で `accounts` を直接操作する。

- 登録：`insert into accounts (email, nickname, password_hash, publish_consent, publish_consent_version)`。この5列だけを指定でき、`id`・`publish_consent_recorded_at`・`created_at`・`updated_at` はDBが決める（指定すると `42501`）。メールの重複は `23505`（`accounts_email_key`）で検出する。
- メールはAPIで前後空白を除き小文字にしてから渡す（DBは小文字・前後空白なし・3〜254文字を検査し、正規化はしない）。ニックネームも前後空白を除いて渡す。
- 再ハッシュ：`update accounts set password_hash = ..., updated_at = now() where id = ...` だけが可能。メール・ニックネーム・同意・文言版は更新できない。
- アカウントの削除権限は `service_role` にない（削除時の扱いは一般公開前の未決事項）。

## 本人履歴の取得（API 16・17）

サーバー用鍵はRLSを迂回するため、所有者条件はDBでは強制されない。**APIが常に検証済みの `JWT.sub` を条件に付ける**（API側の未完事項）。公開ビューは全利用者の公開分の集計用であり、本人履歴には使わない。以下は `tests/verify.sql` の区分12で検証した条件。

一覧（API 16）。`$1` は検証済みの `JWT.sub`、`$2` は任意の店舗、`$3`・`$4` は前ページ最後の `scanned_at`・`menu_id`、`$5` は件数。

```sql
select m.id as menu_id,
       r.google_place_id,
       m.created_at as scanned_at,
       array(select d.translations #>> '{en,name}' from public.dishes d
              where d.menu_id = m.id order by d.position) as dish_names,
       (select count(*) from public.dishes d where d.menu_id = m.id) as dish_count,
       (select count(*) from public.confirmation_sessions s where s.menu_id = m.id) as confirmation_count,
       (m.user_publish_consent and m.restaurant_id is not null
        and exists (select 1 from public.confirmation_sessions s
                     where s.menu_id = m.id and s.publish_consent)) as is_public
  from public.menus m
  left join public.restaurants r on r.id = m.restaurant_id
 where m.account_id = $1                                                -- 必須：所有者
   and ($2::text is null or r.google_place_id = $2)                     -- 任意：店舗（AND）
   and ($3::timestamptz is null or (m.created_at, m.id) < ($3, $4))     -- 任意：カーソル
 order by m.created_at desc, m.id desc
 limit $5;
```

詳細（API 17）。メニューと所有者を同じ条件で取得し、0件なら404（他人・ゲスト・存在しないIDを区別しない）。確認は当該メニューの分だけを返す。

```sql
select m.* from public.menus m where m.id = $menu_id and m.account_id = $1;

select s.id as session_id, s.created_at as confirmed_at, s.publish_consent,
       (s.publish_consent and m.user_publish_consent and m.restaurant_id is not null) as is_public
  from public.confirmation_sessions s
  join public.menus m on m.id = s.menu_id
 where s.menu_id = $menu_id and m.account_id = $1
 order by s.created_at desc, s.id desc;
```

- Supabase SDK（PostgREST）では生SQLを実行できない。上と同じ条件をクエリビルダーで組む（例：`.eq("account_id", sub)`、店舗は `restaurants` の `google_place_id` で絞る、カーソルは `or=(created_at.lt.<t>,and(created_at.eq.<t>,id.lt.<id>))`、`.order("created_at", desc=True).order("id", desc=True)`）。条件が上と一致することをAPIのテストで確認する。
- `account_id` が `NULL` のゲスト解析は、どのアカウントの履歴にも含まれない（登録後に移管しない）。

## API側への引継ぎ

- SQLSTATEからHTTPへの変換はFastAPIで行う。PostgRESTのHTTPステータスはAPI仕様と一致しない（例：`P0002` は500で返る）ため、レスポンス本文の `code`・`message` で判定する。変換表は [API README](../apps/api/README.md#dbエラーの変換) に記載した。
- `is_public` はRPCの戻り値に含まれない。`menus.user_publish_consent`・`restaurant_id` と今回の `publish_consent` からAPIで算出する。
- JWTの署名・期限・`typ`・アカウントの存在確認、メールの正規化、Argon2idの照合・再ハッシュ、登録時の文言版（`2026-10-17-v1`）の付与はAPIの担当。解析時は検証済みの `sub` だけを `p_account_id` に渡し、本文の所有者・同意は受け取らない。
- 本人履歴・本人設定の取得では、所有者条件をAPIが必ず付ける（上記「本人履歴の取得」）。
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
| `accounts` のINSERT権限 | 正本の「`insert`」を登録用5列の列権限に限定し、`id`・同意記録日時・作成／更新日時をAPIから指定できないようにした |
| `accounts` の文字列 | メール・ニックネームは前後空白なしを検査（正規化はAPI）。文言版は1文字以上 |
| 置換RPCの引数・戻り値 | ID配列は `jsonb`（整数以外・null要素も `22023` にするため）、戻り値は昇順の `smallint[]` |
| `save_menu_analysis` のアカウントなし | `P0002`（`account_not_found`）。トークンハッシュ・料理の検証より先に判定 |
