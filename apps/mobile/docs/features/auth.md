# 認証APIとトークン

- 実装: [`src/api/auth.ts`](../../src/api/auth.ts)
- `EXPO_PUBLIC_API_BASE_URL` は `/api/v1` までを含む。未設定またはプレースホルダーなら登録はプレビュー扱い。
- `registerAccount` はメール・ニックネーム・パスワード・公開選択を `POST /auth/register` に送る。
- `loginAccount` はメール・パスワードを `POST /auth/login` に送る。
- 成功後のアカウント用トークンはブラウザの `sessionStorage` に保存する。現状では本人設定・履歴のAPI呼び出しはない。
- 利用規約のチェック状態はAPIへ送られず、同意の証跡としては保存されない。登録時の `publish_consent` と混同しない。
- API契約の正本は [`docs/api.md`](../../../../docs/api.md) と [`contracts/openapi.yaml`](../../../../contracts/openapi.yaml)。ブラウザからSupabaseへ直接アクセスしない。
