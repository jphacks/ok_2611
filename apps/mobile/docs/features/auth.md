# 認証APIとトークン

- 実装: [`src/api/auth.ts`](../../src/api/auth.ts)
- [`src/api/endpoints.ts`](../../src/api/endpoints.ts) の登録・ログイン・アレルゲン保存URLは空欄。全体の流れが完成するまで外部APIへ送らない。各欄には `/api/v1` を含む完全URLを設定する。
- `registerAccount` はメール・ニックネーム・パスワード・公開選択を `POST /auth/register` に送る。
- `loginAccount` はメール・パスワードを `POST /auth/login` に送る。
- 成功後のアカウント用トークンはブラウザの `sessionStorage` に保存する。アレルゲン保存用のPUTコードは [`src/api/allergens.ts`](../../src/api/allergens.ts) にあり、URLを設定するまでは呼ばれない。食事制限設定と履歴のAPI呼び出しは未実装。
- 利用規約にはメニューと店員回答の公開同意を含める。規約同意後の登録時は `publish_consent: true` を送る。利用規約のチェック状態そのものや規約バージョンはAPIへ送られず、規約同意の証跡としては保存されない。
- API契約の正本は [`docs/api.md`](../../../../docs/api.md) と [`contracts/openapi.yaml`](../../../../contracts/openapi.yaml)。ブラウザからSupabaseへ直接アクセスしない。
