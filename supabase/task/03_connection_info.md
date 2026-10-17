# 03の前に：Supabaseの接続情報を渡す手順

[03](03_verify_apply.md) でクラウドの開発プロジェクトへ適用・検証するために必要な情報の渡し方。秘密情報はチャット・文書・Gitに書かない。

## 1. チャットで伝える（秘密ではない）

| 項目 | 確認場所（Dashboard） |
|---|---|
| プロジェクト名 | プロジェクト一覧 |
| Project Ref | Project Settings → General の「Project ID」（URLの `/project/〇〇〇` の部分） |
| リージョン | Project Settings → General |
| 用途 | 開発専用か |
| 既存データ | テーブル・バケットの有無。SQL Editorで作ったものがあれば必ず伝える |

```
プロジェクト名：meelyze-dev
Project Ref：abcdefghijklmnopqrst
リージョン：Northeast Asia (Tokyo)
用途：開発専用、テーブルは未作成
```

## 2. 秘密情報を `supabase/.env.local` に書く

Gitの対象外（`supabase/.gitignore` で除外済み）。`supabase/.env` は除外されないので使わない。

```sh
# supabase/.env.local ― Gitに含めない・チャットに貼らない
SUPABASE_DB_PASSWORD=
SUPABASE_URL=https://<Project Ref>.supabase.co
SUPABASE_SECRET_KEY=
SUPABASE_DB_URL=
# 手順3でログインしない場合だけ
SUPABASE_ACCESS_TOKEN=
```

| 変数 | 取得場所 |
|---|---|
| `SUPABASE_DB_PASSWORD` | 作成時のDBパスワード。忘れたら Project Settings → Database → Reset database password |
| `SUPABASE_URL` | 画面上部「Connect」または Project Settings → Data API |
| `SUPABASE_SECRET_KEY` | Project Settings → API Keys → Secret keys（`sb_secret_` で始まる値） |
| `SUPABASE_DB_URL` | 画面上部「Connect」→「Session pooler」の接続文字列。`[YOUR-PASSWORD]` を実際の値に置き換える |
| `SUPABASE_ACCESS_TOKEN` | Account → Access Tokens で発行（手順3でログインする場合は不要） |

- パスワードに `@` `:` `/` `#` などの記号があると、`SUPABASE_DB_URL` 内では変換が必要（例：`@` → `%40`）。記号なしにすると簡単。
- 「Direct connection」はIPv6専用のことが多く、この端末から繋がらない場合があるため Session pooler を使う。

## 3. CLIにログインする

リポジトリ直下で実行し、開いたブラウザで承認する（手順2で `SUPABASE_ACCESS_TOKEN` を書いた場合は不要）。

```sh
supabase/node_modules/.bin/supabase login
```

## 4. 完了を伝える

チャットで次を伝える。

1. 手順1の情報
2. `supabase/.env.local` を作成したこと
3. CLIにログインしたこと（またはアクセストークンを書いたこと）

以降の作業：`.env.local` の値は表示せず、設定済みかだけを確認する。`supabase link` の後、対象プロジェクトと適用するマイグレーション5件を提示し、承認を得てから `db push` する。

## してはいけないこと

- 秘密情報をチャット・タスク文書・READMEに書く、コミットする
- Dashboardの SQL Editor でテーブル・バケットを先に作る（マイグレーションと競合する）
- `supabase/.env` に書く（Gitの除外対象外）
