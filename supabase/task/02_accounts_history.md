# 02 アカウント・本人設定・読み込み履歴を追加する

状態：未着手。依存：[01のP0構築・検証](01_p0_database.md)。完了後は [03](03_verify_apply.md) へ進める。

## 目的・参照

P0のゲスト利用を維持したまま、登録時公開同意、本人の設定保存、本人の読み込み履歴を支えるDBを完成させる。変更先は `supabase/` 配下のみ。

- [DB仕様](../../docs/database.md)：accounts、本人設定、索引、RPC4つ、読み取り範囲、権限。
- [API仕様](../../docs/api.md)：API 4・8〜12・14〜17。登録・ログイン・JWT・所有者確認はAPI側の担当。
- [要件](../../requirements.md)：R12〜R15、利用者同意は登録時、ゲストの解析は後から移管しない。
- [開発・検証](../../docs/development.md)：アカウント・公開条件・履歴の受入条件。
- [Supabase README](../README.md)：P1のマイグレーション構成。

## 成果物

パスは `supabase/` からの相対パス。

| ファイル | 内容 |
|---|---|
| `migrations/20261017000000_accounts.sql` | アカウント3テーブル、置換RPC2つ、制約・索引・RLS・権限 |
| `migrations/20261017000100_publication_history.sql` | 所有者列・履歴索引・ゲスト制約、解析保存RPCの置換 |
| `tests/verify.sql` | P1の検証を追加し、P0の回帰も確認 |
| `README.md` | 最終RPCの引数・戻り値、履歴の取得条件、適用・検証結果 |

## 作業

1. `accounts`、`account_allergens`、`account_dietary_restrictions` を追加する。メールの小文字・一意・長さ、ニックネーム、Argon2id PHC形式、本人設定の複合PK・外部キーと削除動作を正本どおり定義する。Supabase Authやログインセッション用テーブルは追加しない。
2. 登録時の `publish_consent` は明示booleanを必須とし、falseも保存できるようにする。選択と同じ登録でDB時刻 `publish_consent_recorded_at` とAPI管理の文言版を保存する。`service_role` のaccounts更新権限は `password_hash`・`updated_at` に限定し、同意や本人情報を後から変更できないようにする。
3. `replace_account_allergens` と `replace_account_dietary_restrictions` を作る。対象accounts行を `FOR UPDATE` でロックし、未知・重複IDを拒否して、各設定を別々の1トランザクションで全件置換する。空配列で解除でき、失敗時は元の設定が残る。所有者なしは `P0002`、不正IDは `22023`。戻り値とSQLSTATEの詳細は正本に合わせる。
4. `menus.account_id` とaccountsへの削除制限付きFK、`idx_menus_account_created`、`account_id IS NOT NULL OR user_publish_consent = false` のCHECKを追加する。既存P0データは所有者NULL・同意falseを保つ。
5. 旧 `save_menu_analysis` のシグネチャを削除し、末尾に既定NULLの `p_account_id` を持つ定義へ置換する。アカウントの存在を検証し、登録済み同意をDBからコピーする。同意booleanの引数は追加しない。所有者省略のゲスト呼び出しを維持し、旧オーバーロードを残さない。所有者・同意を含むメニューの不変性も維持する。
6. 追加3テーブルにもRLSを設定する。RPCは `security invoker`、`service_role` だけが実行できるようにし、本人設定のINSERT・DELETEとaccounts行ロックに必要な権限を正本どおり付与する。`PUBLIC`・`anon`・`authenticated` の既定権限を含めて確認する。
7. 本人履歴の取得用SQL例をREADMEに記す。常に `menus.account_id = 検証済み所有者ID` を条件にし、店舗条件はAND、ページングは `created_at DESC, id DESC`。詳細の個別回答は対象メニューの確認だけに絞る。公開ビューの全利用者集計と区別する。サーバー用鍵はRLSを迂回するため、この条件を強制するAPI実装は別担当の未完事項として明記する。

## 完了条件

- [ ] P0からの追加適用と空DBからの全件適用の両方で、最終的に11テーブル・RPC4つ・公開ビュー3つとなる。トリガー用関数はRPC4つの数に含めない。
- [ ] 正規化済みメールの重複、長さ違反、非Argon2id形式を拒否する。登録時同意true／falseは保存でき、欠落／nullは拒否する。
- [ ] 両方の本人設定で全件置換・全解除ができ、未知・重複IDや途中エラーで元の設定を失わない。他アカウントの行に影響しない。
- [ ] 同意true／falseの登録者とゲストの解析を比較し、所有者・同意が仕様どおり固定される。存在しないアカウントは保存できず、選択設定はメニュー・回答へコピーされない。
- [ ] 公開条件の8通り（店舗有無×利用者同意×店員同意）を検証する。同じメニューに公開確認と非公開確認を混在させても、非公開確認の回答はどちらの回答公開ビューにも出ない。
- [ ] 履歴用SQL例で非公開・未確認・店舗未選択も本人分だけ取得でき、店舗・カーソルで絞っても他人やゲストのメニューを含まない。
- [ ] `service_role` の所有者・同意・スナップショット更新を拒否し、accountsの再ハッシュ用更新と両置換RPCは成功する。
- [ ] 01のゲスト解析・店員確認の検証が引き続き成功する。並行保存と実SDK経由の検証は03で完了させる。

JWTの署名・期限・本人確認、メール正規化・パスワード照合、HTTPステータスへの変換、公開APIの集計・返却項目制限はAPI実装に残す。DB検証だけでこれらを動作確認済みにしない。
