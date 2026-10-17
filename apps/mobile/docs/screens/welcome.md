# 起動画面

- 実装: [`app/index.tsx`](../../app/index.tsx)
- 役割: 新規登録、ログインへの入口。
- ロゴ: ユーザー提供の `Meelyze _icon.webp` を中央に表示する。起動画面には左上の横長ロゴを表示しない。
- 遷移: `Create account` → `/onboarding`、`Log in` → `/login`。
- 現状: 入口は表示できる。撮影・解析は未実装。
