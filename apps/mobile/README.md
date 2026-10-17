# apps/mobile

Meelyze+ のフロントエンド。React Native + Expoで作るスマートフォン向けWebアプリ。利用者の端末1台で完結し、店員は利用者が差し出した端末の「店員確認カード」で回答する。iOS／Androidネイティブ版は対象外。

> 2026-10-18時点：主要画面・APIクライアント・沖縄メニューのプレビューを作成済み。外部APIの接続先は未設定で、実データによる一連の操作は未結合。店員回答はブラウザ内への仮保存であり、FastAPIへの保存・公開はまだ行わない。

作業時は [CLAUDE.md](CLAUDE.md) を参照する。要件・API・画面の正本は [要件](../../requirements.md)、[開発・検証](../../docs/development.md)、[画面仕様](../../docs/screens.md)、[API仕様](../../docs/api.md)。本書は現在のモバイル実装と、未結合・未実装の範囲を説明する。

## 技術スタック

| 用途 | 現在の構成 | 備考 |
|---|---|---|
| 言語 | TypeScript 5.9.3 | `tsc --noEmit` で型チェック |
| 実行環境 | Node.js 24系 | `package.json` は `>=24.3.0 <25`、`.nvmrc` は `24` |
| フレームワーク | Expo SDK 58（58.0.14）、React 19.3.0、React Native 0.88.0 | `react-native-web` でWeb向けに出力 |
| ルーティング | Expo Router | `app.json` は `web.output: "static"`、`apiRoutes: true` |
| 外部API呼び出し | `fetch` | FastAPIを呼ぶ。Supabase・Storage・Gemini・DBへ直接接続しない |
| 同一オリジンの補助API | Expo Router API Routes | 選択項目・店員回答の入力検証、メニュー表示用データの整形 |
| 撮影・画像選択 | `expo-camera` の `CameraView`、ブラウザのファイル入力 | カメラが使えない場合はJPEG／PNGを選択 |
| 画像加工 | ブラウザのCanvas API | JPEGへの変換・縮小・圧縮 |
| 端末内の保存 | 主に `sessionStorage` | 撮影画像はReact Contextのメモリ内。店員同意の記憶には一部 `localStorage` も使用 |
| 表示言語 | 利用者向け英語・店員向け日本語 | 文言は各画面・`src/content/` 等に配置。`src/i18n/` は未作成 |
| 地図・位置情報 | 未実装 | `/map` は仮画面。Google Maps・Geolocation APIは未接続 |
| デプロイ設定 | Vercel、`expo-server` | Root Directoryは `apps/mobile`。API Routesを処理するサーバーを含む |

依存の解決済みバージョンは [package-lock.json](package-lock.json) で管理する。依存変更時はロックファイルを更新し、型チェックとWebビルドを確認する。

## 画面と実装状況

| 画面・ルート | 現在の状態 |
|---|---|
| ① `/`、② `/onboarding` | 開始画面、利用規約モーダルと同意導線 |
| ③ `/register` | 入力検証と登録クライアントを作成済み。API未設定時は端末内のプレビュー情報を保存して設定画面へ進む。アカウント・トークンは発行しない |
| ④ `/login` | ログイン画面とクライアントを作成済み。外部APIは未接続 |
| ⑤ `/profiles/setup` | アレルゲン29品目から1品目以上を選択。補助APIで検証後、タブ内に保存。外部API設定時の本人設定保存処理あり |
| ⑥ `/map` | `Under construction.` の仮画面。店舗確認画面へ進める |
| ⑧ `/places/select` | 引き継がれた店舗候補の確認、またはスキップ。候補を検索・取得する処理は未実装 |
| ⑨ `/capture`、⑩ `/capture/preview` | 撮影・画像選択、画像加工、写真確認、再撮影、解析リクエスト処理を作成済み。解析APIは未接続 |
| ⑪ `/menu?id=<menu_id>`、⑫ 詳細シート | 解析結果のキャッシュ／API取得結果から一覧と詳細を表示。確認済み料理とAI推定の料理を分ける |
| ⑬ `/confirm?id=<menu_id>&dish_id=<dish_id>`、⑭ 同意モーダル | 1料理×選択アレルゲンの4択回答。全問回答を検証して同意を取得し、タブ内へ仮保存。記憶済みの同意を再利用する処理あり |
| ⑮ `/result?id=<menu_id>&dish_id=<dish_id>` | タブ内の仮保存回答を表示し、同じメニューの一覧へ戻る。FastAPIの確認セッションによる結果取得は未結合 |
| ⑯ `/profiles`、⑰ `/profiles/edit` | タブ内の本人情報・アレルゲンの表示と編集。本人情報・設定のサーバーからの取得、読み込み履歴は未実装 |

現在のモバイル方針では食事制限4項目の選択欄とゲスト導線を除外し、実画像の解析にはログイン済みのアカウント用トークンを必須としている。複数人プロファイルの切替は未実装。全体仕様との差分は [モバイル開発ガイド](CLAUDE.md) も参照する。

## ディレクトリ

| パス | 内容 |
|---|---|
| `app/` | Expo Routerの画面・レイアウト・`+api.ts` の補助API |
| `src/api/` | FastAPIの接続先、認証・設定保存・解析・結果取得のクライアントと型 |
| `src/features/capture/` | 撮影画像のメモリ保持、画像加工、解析結果のタブ内保存 |
| `src/features/profile/` | アレルゲン選択UIとタブ内保存 |
| `src/features/menu-results/` | 表示用データの整形、料理詳細シート、デモデータ、店員回答・同意の仮保存 |
| `src/components/` | ボタン、入力欄、共通ページ、ロゴ、利用規約モーダル |
| `src/content/` | アレルゲンの選択肢、利用規約の文面 |
| `src/theme.ts` | 共通の色定義 |
| `assets/` | アプリアイコン・ロゴ |
| `api/index.ts` | VercelからExpoのサーバー処理へ渡すハンドラー |
| `.env.example`、`vercel.json` | 環境変数の例、Vercelのビルド・実行設定 |

## セットアップ・コマンド

Node.js 24系を使用する。リポジトリのルートから、初回は次を実行する。`.env` が既にある場合は上書きせず、必要な項目だけ追加する。

```sh
cd apps/mobile
nvm use
npm ci
cp -n .env.example .env
npm start
```

`nvm` を使用しない場合は、別の方法で `package.json` のNode要件を満たす環境を用意する。開発サーバーのURLは起動時の出力を参照する。

| コマンド | 用途 |
|---|---|
| `npm start` | `expo start --web` による開発サーバー |
| `npm run typecheck` | TypeScriptの型チェック |
| `npm run build:web` | `expo export --platform web` によるWebビルド |

スマートフォンのカメラ確認はHTTPSの環境で行う。ローカルホストでの開発とは条件が異なるため、LAN上のHTTP URLでカメラが使えることを前提にしない。

## API・環境変数

### FastAPIの接続先

接続先は [src/api/endpoints.ts](src/api/endpoints.ts) に集約している。現在は全項目が空文字で、未設定の外部APIへの送信は行わない。実URLの設定と結合確認は今後の作業となる。

| キー | 接続時に設定するURL・状態 |
|---|---|
| `register` | `POST /api/v1/auth/register` の完全なURL |
| `login` | `POST /api/v1/auth/login` の完全なURL |
| `saveAllergens` | `PUT /api/v1/me/allergens` の完全なURL |
| `analyzeMenu` | `POST /api/v1/menus/analyze` の完全なURL |
| `getMenu` | `/api/v1/menus` までのURL。クライアントがメニューIDを追加 |
| `createConfirmation` | `/api/v1/menus` までのURLを置く予約欄。店員回答をFastAPIへ送信する処理は未実装のため、URL設定だけでは接続されない |
| `getDishDetails` | 将来用の予約欄。APIの契約・パスは未定義で、現状は解析結果から詳細を表示 |

`EXPO_PUBLIC_API_BASE_URL` は現在のコードでは使用していない。以前の実装方針のように、この環境変数だけ設定しても接続先は変わらない。結合時はFastAPI側の `ALLOWED_ORIGINS` にフロントのオリジンを設定する。

### 環境変数

| 名前 | 現在の扱い |
|---|---|
| `EXPO_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY` | `.env.example` に予約。地図が未実装のため未使用。利用開始時はMaps JavaScript APIとHTTPリファラーを制限する |

`EXPO_PUBLIC_` の値はブラウザへ公開される。Supabaseの秘密鍵・GeminiのAPIキー等はFastAPI側で管理し、ここには設定しない。

### Expo側の補助API

次のルートはフロントと同じオリジンにあり、FastAPIの業務APIとは別の処理を行う。

| ルート | 処理 |
|---|---|
| `POST /profiles/validate` | アレルゲンIDの範囲・重複・1件以上の選択を検証 |
| `POST /menu-summary` | メニュー結果と選択IDを受け取り、一覧・詳細向けの表示データへ整形 |
| `GET /menu-summary?demo=okinawa` | 沖縄メニューの固定データから表示用データを返す |
| `POST /confirm-validate` | 料理・対象アレルゲン・4択回答の過不足を検証。DBには保存しない |

## 撮影・解析・結果表示

- 撮影直後の画像はメモリ内に保持し、⑩の `Analyze` を押したときだけ外部解析APIへ送る。再読込すると撮影画像は失われる。
- JPEG／PNGを受け付け、2000万画素を超える画像は拒否する。送信前に縮小・JPEG圧縮を行い、2 MiB以下にする。
- 解析は `multipart/form-data` で `image`、繰り返しの `allergen_ids`、`locale=en`、店舗選択済みなら `google_place_id` を送る。アカウント用Bearerが必須で、401後にゲストへ切り替えて再送しない。
- 解析の待機上限は45秒。二重送信を防ぎ、失敗した解析POSTを自動再送しない。成功後の解析用トークンはURLに載せず、結果とともに `sessionStorage` へ保存する。
- AI候補の判定、過去回答の集計・時間による重み・スコア、注意フラグの計算はFastAPI側の担当。Expo側の `summary.ts` は返り値を表示用に整形し、AIと履歴を合成した予測値は計算しない。
- 現在の一覧は `current_answer` の有無で区画を分け、AIまたは店員回答のバッジと `notices` による再確認案内を表示する。詳細はAIの説明・根拠と今回の店員回答を表示する。`store_history` の件数・日時・スコアを表示するUIは未実装。
- 原材料候補は現行APIの返却欄がないため、詳細の `likelyIngredients` は空配列。未提供であることと店員への確認案内を表示する。

AIの推定と店員の回答は区別する。「安全」「食べられる」と断定せず、`unknown` や履歴なしを不使用と解釈しない。画像・トークン・個人情報・アレルゲン選択をログへ記録しない。

## プレビューと端末内保存

開発サーバー起動後、`/menu?demo=okinawa` を開くと、固定された沖縄メニュー14品を小麦（ID `3`）・豚肉（ID `23`）の対象で表示する。画像解析APIは呼ばない。

料理を選択し、詳細 → `Ask staff` → 4択回答 → 同意 → 結果 → 一覧、の画面を確認できる構成。初期データには店員回答・過去回答はなく、操作で入力した回答だけをタブ内に仮保存する。実際の店舗確認や本番DBへの保存を示すものではない。

| データ | 保存先 |
|---|---|
| 撮影・選択した画像 | `CaptureContext` のメモリ内 |
| 選択アレルゲン、本人表示情報、アカウント用トークン・ID | `sessionStorage` |
| 解析結果・解析用トークン | `sessionStorage`（メニューIDごと） |
| 仮の店員回答・回答日時・同意 | `sessionStorage`（メニューIDごと） |
| 店員同意の記憶 | デモ／アカウントIDなしでは `sessionStorage`、アカウントIDありでは `localStorage` |

実API結合時には、現在の仮保存を確認APIでの一括保存へ置き換え、保存成功後の回答・日時・公開可否をサーバー応答に基づいて表示する。仮保存は過去回答の集計や公開データへ反映されない。

## Vercel設定

現在の [vercel.json](vercel.json) は次の設定になっている。

- Root Directory：`apps/mobile`
- Build Command：`expo export -p web`
- Output Directory：`dist/client`
- 全リクエストを `/api/index` へ渡し、[api/index.ts](api/index.ts) の `expo-server/adapter/vercel` が `dist/server` を使って処理

単に静的ファイルを置くSPA構成ではなく、入力検証・表示整形のAPI Routesも必要になる。デプロイ時は各画面の直接アクセスに加え、上記の補助APIが応答することを確認する。

## 検証と残作業

本書作成時はソースコード・設定・npm scriptsとの照合を行った。依存インストール、型チェック、Webビルド、ブラウザ実機・公開環境の動作確認はこの作業では実施していない。

結合・公開前に次を確認する。

- `npm ci`、`npm run typecheck`、`npm run build:web` の成功。
- スマートフォンでの撮影、カメラ権限拒否時の画像選択、写真確認・再撮影。
- 実APIによる登録・ログイン・本人設定保存・解析・結果再取得。タイムアウト・期限切れ・失敗時に自動再送しないこと。
- 店員回答のFastAPIへの一括保存、同意・公開条件、未回答の拒否、明示的な「分からない」、二重送信、保存後の一覧への反映。
- 店舗検索・位置情報・地図、過去回答の件数／日時表示、本人履歴などの未実装範囲。

食事制限・ゲスト利用・複数人プロファイルを含む全体要件の達成状況は、現行モバイル方針との差分を整理したうえで判断する。
