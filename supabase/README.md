# Supabaseのセットアップ

SQL・Storage設定・検証SQLは未作成。構造と制約の正本は [DB仕様](../docs/database.md)、検証項目は [開発・検証](../docs/development.md#検証) を参照する。以下は実装時の配置と手順。

## 作成するファイル

```
supabase/
├── migrations/      # SQL・DB変更履歴。ファイル名順に適用する
├── tests/           # 開発DB用の検証SQL（マイグレーションではない）
└── README.md        # このファイル
```

| ファイル | 内容 |
|---|---|
| `migrations/20261016000000_init_schema.sql` | 確認用8テーブル（食事制限のマスタ・回答を含む）、トリガー、`save_menu_analysis`・`complete_confirmation_session`、公開ビュー、RLS・権限 |
| `migrations/20261016000100_seed_master_data.sql` | アレルゲン29種・食事制限4種 |
| `migrations/20261016000200_storage.sql` | 非公開バケット |
| `migrations/20261017000000_accounts.sql` | 登録時公開同意を含むアカウント3テーブル、本人設定の置換RPC2つ、RLS・権限（P1） |
| `migrations/20261017000100_publication_history.sql` | `menus.account_id` のFK・履歴索引・ゲストの同意false制約、`save_menu_analysis` の所有者引数追加と登録時同意のコピー（P1） |
| `tests/verify.sql` | 開発DB用の検証。最後にロールバックする |

## 適用手順

Supabase CLIを導入し、リポジトリ直下で対象プロジェクトにリンクしてから適用する。

```sh
supabase link --project-ref <project-ref>
supabase db push
```

- 同じ環境で、SQL Editorからの手動実行と `db push` を混在させない。適用履歴が食い違う。
- 適用済みのマイグレーションは編集しない。変更は新しいタイムスタンプ（UTC、`YYYYMMDDHHMMSS_内容.sql`）のファイルで追加する。
- 初回マイグレーションは新しい環境専用である。同名のテーブルがあると失敗し、旧DDLからの上書き移行には使えない。
- 必須マスタはマイグレーションに含め、環境間で同じIDと値を適用する。`seed.sql` も `db push --include-seed` でリモート適用できるが、本プロジェクトの必須マスタには使わない。[Supabaseの適用手順](https://supabase.com/docs/guides/deployment/database-migrations)
- 本番環境で実行する前、または既存のテーブルを削除する前には、対象の環境と変更内容を確認する。
