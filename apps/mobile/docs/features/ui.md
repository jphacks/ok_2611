# 共通UI

| ファイル | 役割 |
|---|---|
| [`assets/meelyze-icon.webp`](../../assets/meelyze-icon.webp) | 起動画面の正方形ロゴ。ユーザー提供の `Meelyze _icon.webp` を使用 |
| [`assets/meelyze-header.webp`](../../assets/meelyze-header.webp) | 各画面左上の横長ロゴ。ユーザー提供の `Meelyze _header.webp` を使用 |
| [`assets/meelyze-icon.png`](../../assets/meelyze-icon.png) | ExpoのアプリアイコンとWebのfavicon用。Expoの推奨形式に合わせてPNGを維持 |
| [`src/components/BrandLogo.tsx`](../../src/components/BrandLogo.tsx) | 表示場所に応じて正方形または横長のWebPロゴを表示 |
| [`src/components/Page.tsx`](../../src/components/Page.tsx) | 各画面のスクロール領域、タイトル、最大幅を揃える。起動画面以外に左上の横長ロゴを表示 |
| [`src/components/PrimaryButton.tsx`](../../src/components/PrimaryButton.tsx) | 主ボタンと副ボタン。主色は `#008561` |
| [`src/components/FormField.tsx`](../../src/components/FormField.tsx) | 入力欄のラベル、入力タイプ、エラー表示 |
| [`src/theme.ts`](../../src/theme.ts) | Verde Pompeiano `#008561` を含む色定義 |

画面固有の配置・文言は各 `app/*.tsx` に置く。
