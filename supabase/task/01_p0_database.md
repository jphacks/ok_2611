# 01 P0のDB基盤を構築する

状態：SQL作成・ローカル検証済み（2026-10-17）。クラウドへの適用、並行実行・SDK・実Storage操作の検証は未完で [03](03_verify_apply.md) で行う。実行手順・結果・実装で決めた事項は [README](../README.md) に記録した。依存：なし。[00の利用者側準備](00_user_setup.md) と並行して進める。クラウドへの接続には00の完了が必要。完了後は [02](02_accounts_history.md) → [03](03_verify_apply.md) の順に進める。

## 目的・対象

ゲストによる解析保存・店員確認を支えるDBと非公開Storageを作る。タスク作成時点の `supabase/` にはREADMEのみがあり、SQL・設定・テストは未作成。接続先の実DBの状態は未確認。

00は利用者側のアカウント・接続準備、01〜03は実装・検証・適用を扱う。リポジトリの変更先は全タスクで `supabase/` 配下のみ。DB構築の完了は03の適用・検証までとし、今回作成したタスク文書を実装済みの根拠にしない。

## 参照

- [DB仕様](../../docs/database.md)：テーブル、トリガー、RPC、公開ビュー、権限、Storage、固定マスタの正本。
- [API仕様](../../docs/api.md)：共通エラー、API 4〜7・13、入力上限、APIとDBの責任分担。
- [要件](../../requirements.md)：R02〜R09、公開同意とゲスト利用。
- [開発・検証](../../docs/development.md)：構成、P0優先、DBの検証項目。
- [Supabase README](../README.md)：マイグレーションの分割と適用順。

列定義やマスタ一覧は転記せず正本を参照する。仕様の矛盾・不足は該当タスクに記録し、対象外の資料を変更しない。

## 成果物

パスは `supabase/` からの相対パス。

| ファイル | 内容 |
|---|---|
| `config.toml` | 開発用Supabaseの再現に必要な設定。秘密値を含めない |
| `migrations/20261016000000_init_schema.sql` | P0の8テーブル、索引、トリガー、RPC2つ、公開ビュー3つ、RLS・権限 |
| `migrations/20261016000100_seed_master_data.sql` | アレルゲン29種・食事制限4種の固定マスタ |
| `migrations/20261016000200_storage.sql` | `menu-images` の非公開設定と既存設定の検査 |
| `tests/verify.sql` | P0の検証。トランザクション内で実行し、最後にロールバック |
| `README.md` | 開発環境の準備・P0の実行手順・検証結果 |

マイグレーション名は既存READMEの計画に従う。着手時に適用履歴を再確認し、既に適用済みのファイルがあれば編集せず、新しいマイグレーションで対応する。

## 作業

1. [公式手順](https://supabase.com/docs/guides/local-development/cli/getting-started) に従ってSupabase CLIを導入し、バージョンを記録する。リポジトリ内の依存・設定ファイルは `supabase/` に限定する。コンテナ実行環境を確認し、リポジトリ直下を作業ディレクトリとして `supabase init`・`supabase start` で空のローカル開発環境と実行手順を用意する。既存の設定があれば上書きせず確認する。以後のSQLはマイグレーション経由で管理し、同じ環境でSQL Editorの手動適用と混在させない。クラウドのプロジェクト作成・管理用認証は00、リンク・適用は03で扱う。
2. `restaurants`、`menus`、`dishes`、`allergens`、`dietary_restrictions`、`confirmation_sessions`、`confirmation_answers`、`confirmation_dietary_answers` を作る。正本の型・NULL・既定値・CHECK・外部キー・一意制約・索引・不変性トリガーを反映する。`menus.user_publish_consent` は初期から持ち、`account_id` は02で追加する。
3. 固定マスタをマイグレーションに含める。アレルゲンの既存ID 1〜10を維持し、IDと表示順を区別する。29品目の分類は9＋20、食事制限は別ID空間の4種とする。`seed.sql` に必須データを移さない。
4. `save_menu_analysis` のP0版を作る。所有者引数を持たず、利用者同意は必ずfalse。1〜20料理を配列順の `position` で保存し、途中失敗でメニューも含めて戻す。解析トークンは小文字16進64文字のハッシュだけを保存し、期限は既定24時間とする。
5. `complete_confirmation_session` を作る。メニューを行ロックしてトークン・期限を検証し、確認と両回答配列を原子的に保存する。合計1〜50回答・料理の和集合1〜10件、各配列の直積、両配列の料理集合一致、重複・未知ID・所属・版・未回答を検証する。片側だけ空と明示的な `unknown` は許可し、両方空・欠落・nullは拒否する。同一 `request_id` は両配列の順序を正規化して店員同意と比較し、再送判定の後に新規5回の上限を判定する。SQLSTATE・戻り値は正本に合わせる。
6. `published_menus`、`published_confirmation_answers`、`published_dietary_answers` を正本の列で作る。店舗あり・利用者同意true・対象確認の店員同意trueを必須とする。P0の通常保存は利用者同意falseのため公開行は生じない。公開を試すために同意を偽造せず、全組合せの検証は02以降で行う。
7. 全8テーブルのRLSを有効にし、`PUBLIC`・`anon`・`authenticated` のテーブル／ビュー／関数への権限を除去する。RPCは `security invoker`、ビューは `security_invoker=true`。`service_role` の権限は正本の表に限定し、行ロック用の `menus.id` の列UPDATE権限と更新拒否トリガーを両立させる。
8. 非公開バケット `menu-images` を作る。上限2,097,152バイト、JPEG／PNGのみ、クライアント向けポリシーなし。既存バケットの設定が異なる場合は例外で停止する。画像削除はStorage APIを使う手順とし、`storage.objects` を直接DELETEしない。

## 完了条件

以下はローカル開発環境（Supabase CLI 2.121.0・PostgreSQL 17.11）での確認。

- [x] 空の開発DBへP0の3マイグレーションを順番に適用でき、8テーブル・RPC2つ・公開ビュー3つ・マスタ29＋4件が正本と一致する。
- [x] 正常な解析とアレルゲンのみ／食事制限のみ／両方の確認が保存でき、料理順・`unknown`・不同意が保持される。
- [x] 料理0／21件、回答0／51件、料理11件、未知ID・重複・直積不足・別メニュー料理・版違い・欠落／nullを拒否し、部分保存が残らない。
- [x] 他メニューのトークン、不正ハッシュ、期限切れを拒否する。同内容の並び替え再送は行を増やさず、内容・店員同意の変更は競合になる。5回到達後の再送は成功し、新規6回目と期限切れの再送は拒否する。
- [x] `service_role` でRPCと行ロックが成功し、スナップショットのUPDATEは拒否される。`anon`・`authenticated` は直接読取・書込・RPC実行ができない。
- [x] ゲストの確認は店員同意ありでも公開されず、画像・トークンハッシュが公開ビューに含まれない。
- [x] 開発環境でバケット設定を確認する。実Storage操作・並行実行の検証は03で完了させる。
- [x] `tests/verify.sql` は失敗を検出でき、成功時も最後にロールバックする。実行環境・コマンド・結果を記録する。

画像の画素検証・VLM JSONの詳細検証・`name_key` の生成・予測計算・Storage保存後のDB失敗時の画像削除処理はAPI側の担当。DBでは正本の制約を実装し、API側に残る事項を引き継ぐ。
