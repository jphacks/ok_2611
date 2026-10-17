# apps/mobile

Meelyze+ のフロントエンド。React Native + Expo で作り、Web版として公開する。利用者のスマートフォン1台で完結し、店員は利用者が差し出した端末の「店員確認カード」を操作して回答する。

> Expo Webの土台と①起動・②注意事項・③新規登録・④ログイン・⑤アレルゲンの選択、⑨撮影・⑩撮影確認の画面を作成済み。解析などのP0機能はまだ未実装。

## 現在の動作

- Node.js 24.3以上の24系を使用する（`.nvmrc`）。`npm ci`で依存をインストールする。
- `npm run start`でWeb版を起動する。`npm run typecheck`と`npm run build:web`で確認する。Web出力はビルド後に `npx expo serve` で配信する。Pythonの静的ファイルサーバーではAPI Routesは動かない。
- 外部APIの接続先は [`src/api/endpoints.ts`](src/api/endpoints.ts) の4欄（登録・ログイン・アレルゲン保存・メニュー解析）を空欄にしている。全画面の流れが完成した後、各URLを `/api/v1` を含む完全なアドレスで設定する。空欄の間は外部APIへ送信しない。
- 登録URLが空欄なら入力確認後に⑤のプレビューへ進み、アカウントは作成しない。ログインURLが空欄ならログイン送信をしない。URLを設定した後はそれぞれのPOSTを呼び、成功時にアカウント用トークンをこのタブの `sessionStorage` に置く。
- ②利用開始前の説明画面で利用規約と安全上の注意を読み、同意する。③新規登録で同じ確認は繰り返さない。メニューと店員回答の公開同意は規約に含め、登録時に `publish_consent: true` を送る。
- ⑤では29品目のアレルゲンから1品目以上を選択する。食事制限欄は表示しない。`Save profile` はExpo Routerのサーバールートで空選択を拒否する。保存URLが空欄なら保存せず、入力確認後に作成中の `/map` 仮画面へ進む。URL設定後はアカウント用トークンを使うPUTの成功後に進む。
- `/map` の `Scan a menu` から⑧店舗確認／スキップ、⑨撮影、⑩写真確認へ進める。`expo-camera` で撮影するかJPEG／PNGを選ぶ。`Retake` は画像を破棄して⑨へ戻る。`Analyze` は選択したアレルゲンIDと写真をAPI 4へ送る処理を備え、URL空欄時は送信せず案内する。成功時は⑪で結果の概要を表示する。

## 実装メモ

画面・機能ごとの役割と現状は [docs/README.md](docs/README.md) を参照する。画面を追加・変更したら対応するMarkdownも更新する。

## 技術スタック

| 用途 | 技術 | 備考 |
|---|---|---|
| 言語 | TypeScript | |
| フレームワーク | React Native + Expo | Web向けに出力（react-native-web）。Expo SDKに対応するNodeを固定する |
| ルーティング | Expo Router | `web.output: "static"`＋API Routes。画面とサーバールートを一緒に配信する |
| API呼び出し | `fetch` | `apps/api` だけを呼ぶ。Supabaseへ直接アクセスしない |
| 位置情報 | ブラウザのGeolocation API | HTTPSが必要。拒否された場合はスキップを案内する |
| 撮影・画像選択 | `expo-camera` の `CameraView`、ブラウザのファイル入力 | JPEGへ変換し送信前に縮小する |
| 地図（P1） | Google Maps JavaScript API | ブラウザ用キー（リファラー制限）。React用のラッパーは未選定 |
| 端末内の保存 | sessionStorage | アカウント用トークン、選択したアレルゲンID、解析結果と解析用トークンをタブ内に保持。画像本体はメモリのみ |
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
| `EXPO_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` | 地図表示用（P1）。Maps JavaScript APIとHTTPリファラーに制限したキー |

## コマンド

このディレクトリで実行する。

| コマンド | 用途 |
|---|---|
| `npx expo start --web` | 開発サーバー |
| `npx expo export --platform web` | Webビルド |

位置情報とカメラはHTTPSでないと使えないため、スマートフォンでの確認はVercelのプレビューURLなどHTTPSの環境で行う。
