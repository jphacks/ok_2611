# mobile 実装メモ

`apps/mobile` の画面と機能を探すための索引。現在動く範囲と未実装を分けて記す。変更時は該当ファイルの説明も更新する。

## 画面

| ソース | 説明 |
|---|---|
| [`app/index.tsx`](../app/index.tsx) | [起動画面](screens/welcome.md) |
| [`app/onboarding.tsx`](../app/onboarding.tsx) | [利用開始前の説明](screens/onboarding.md) |
| [`app/register.tsx`](../app/register.tsx) | [新規登録](screens/register.md) |
| [`app/terms.tsx`](../app/terms.tsx) | [利用規約と安全上の注意](screens/terms.md) |
| [`app/login.tsx`](../app/login.tsx) | [ログイン](screens/login.md) |
| [`app/profiles/setup.tsx`](../app/profiles/setup.tsx) | [設定の仮画面](screens/profile-setup.md) |
| [`app/_layout.tsx`](../app/_layout.tsx) | Expo Router の共通 Stack。ヘッダーは非表示 |

## 共通機能

| ソース | 説明 |
|---|---|
| [`src/api/auth.ts`](../src/api/auth.ts) | [認証APIとトークン](features/auth.md) |
| [`src/components/`](../src/components/)・[`src/theme.ts`](../src/theme.ts) | [共通UI](features/ui.md) |

画面遷移・APIの正式な仕様はリポジトリ共通の [`docs/screens.md`](../../../docs/screens.md) と [`docs/api.md`](../../../docs/api.md) を参照する。この索引は `apps/mobile` の実装状態を記録する。
