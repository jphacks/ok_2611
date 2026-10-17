# mobile 実装メモ

`apps/mobile` の画面と機能を探すための索引。現在動く範囲と未実装を分けて記す。変更時は該当ファイルの説明も更新する。

## 画面

| ソース | 説明 |
|---|---|
| [`app/index.tsx`](../app/index.tsx) | [起動画面](screens/welcome.md) |
| [`app/onboarding.tsx`](../app/onboarding.tsx) | [利用開始前の説明](screens/onboarding.md) |
| [`app/register.tsx`](../app/register.tsx) | [新規登録](screens/register.md) |
| [`src/components/TermsModal.tsx`](../src/components/TermsModal.tsx) | [利用規約と安全上の注意のモーダル](screens/terms.md) |
| [`app/login.tsx`](../app/login.tsx) | [ログイン](screens/login.md) |
| [`app/profiles/setup.tsx`](../app/profiles/setup.tsx) | [アレルゲンの選択](screens/profile-setup.md) |
| [`app/map.tsx`](../app/map.tsx) | [マップ仮画面](screens/map.md) |
| [`app/places/select.tsx`](../app/places/select.tsx) | [店舗確認・スキップ](screens/capture.md) |
| [`app/capture/index.tsx`](../app/capture/index.tsx)・[`app/capture/preview.tsx`](../app/capture/preview.tsx) | [撮影・撮影確認](screens/capture.md) |
| [`app/menu.tsx`](../app/menu.tsx) | [解析結果の概要](screens/capture.md) |
| [`app/_layout.tsx`](../app/_layout.tsx) | Expo Router の共通 Stack。ヘッダーは非表示、撮影画像を画面間で保持 |

## 共通機能

| ソース | 説明 |
|---|---|
| [`src/api/auth.ts`](../src/api/auth.ts) | [認証APIとトークン](features/auth.md) |
| [`src/content/preferences.ts`](../src/content/preferences.ts) | [アレルゲン29品目の選択肢](screens/profile-setup.md) |
| [`src/features/capture/CaptureContext.tsx`](../src/features/capture/CaptureContext.tsx) | [撮影画像の一時保持](screens/capture.md) |
| [`src/api/menus.ts`](../src/api/menus.ts) | [解析APIへの送信](screens/capture.md) |
| [`src/components/`](../src/components/)・[`src/theme.ts`](../src/theme.ts) | [共通UI](features/ui.md) |

画面遷移・APIの正式な仕様はリポジトリ共通の [`docs/screens.md`](../../../docs/screens.md) と [`docs/api.md`](../../../docs/api.md) を参照する。この索引は `apps/mobile` の実装状態を記録する。
