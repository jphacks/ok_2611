# ログイン

- 実装: [`app/login.tsx`](../../app/login.tsx)
- 役割: メールとパスワードでログインする。
- API設定時: [`src/api/auth.ts`](../features/auth.md) の `POST /auth/login` を呼び、成功したら `/profiles/setup` に進む。
- API未設定時: プレビューである旨のエラーを表示する。
- 現状: 失敗時はメッセージを表示する。ログイン後の設定・履歴は未実装。
