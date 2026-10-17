# apps/mobile

Meelyze+ のフロントエンド。React Native + Expo で作り、Web版として公開する。利用者のスマートフォン1台で完結し、店員は利用者が差し出した端末の「店員確認カード」を操作して回答する。

> アプリ本体は未作成。以下は実装方針であり、記載のコマンドや動作は確認していない。

## 技術スタック

| 用途 | 技術 | 備考 |
|---|---|---|
| 言語 | TypeScript | |
| フレームワーク | React Native + Expo | Web向けに出力（react-native-web）。Expo SDKに対応するNodeを固定する |
| ルーティング | Expo Router | `web.output: "single"`（SPA） |
| API呼び出し | `fetch` | `apps/api` だけを呼ぶ。Supabaseへ直接アクセスしない |
| 位置情報 | ブラウザのGeolocation API | HTTPSが必要。拒否された場合はスキップを案内する |
| 撮影・画像選択 | ブラウザのファイル入力（カメラ起動） | 送信前に縮小する |
| 地図（P1） | Google Maps JavaScript API | ブラウザ用キー（リファラー制限）。React用のラッパーは未選定 |
| 端末内の保存 | localStorage／sessionStorage | プロファイルはlocalStorage、各トークンはsessionStorage |
| 多言語 | 利用者向け英語・店員向け日本語の固定辞書（`src/i18n/`） | 利用者の画面は英語のみ、店員確認カードは日本語 |
| デプロイ | Vercel | Root Directoryは `apps/mobile` |

- 依存は、実際に動作を確認したバージョンをロックファイルに固定する。選んだライブラリは [開発・検証](../../docs/development.md) に記録する。
- ディレクトリ名は `mobile` だが、今回の対象はスマートフォンのブラウザで使うWeb版だけ。iOS／Androidネイティブ版とその動作保証は対象外。

仕様・優先度・検証項目は [開発・検証](../../docs/development.md) から参照する。

## 作成するディレクトリ

| パス | 内容 |
|---|---|
| `app/` | Expo Routerの画面 |
| `src/api/` | APIクライアントとDTO |
| `src/features/` | 初期設定、アレルゲン・食事制限、店舗確認、撮影確認、解析・予測、店員回答・同意・結果、マップ（P1）、アカウント（P1）の処理 |
| `src/i18n/` | 利用者向け英語・店員向け日本語の固定辞書 |
| `.env.example` | 環境変数の例 |
| `vercel.json` | Vercel用の設定（SPAのリライト） |

## 環境変数

`.env.example` を `.env` にコピーする。`EXPO_PUBLIC_` で始まる値はブラウザへ公開されるため、秘密値を入れない。

| 名前 | 内容 |
|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | APIの `/api/v1` を含むURL |
| `EXPO_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` | 地図表示用（P1）。Maps JavaScript APIとHTTPリファラーに制限したキー |

## コマンド

このディレクトリで実行する。

| コマンド | 用途 |
|---|---|
| `npx expo start --web` | 開発サーバー |
| `npx expo export --platform web` | Webビルド |

位置情報とカメラはHTTPSでないと使えないため、スマートフォンでの確認はVercelのプレビューURLなどHTTPSの環境で行う。
