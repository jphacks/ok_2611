# apps/mobile

Meelyze+ のフロントエンド。React Native + Expoで作るスマートフォン向けWebアプリ。利用者の端末1台で完結し、店員は利用者が差し出した端末の「店員確認カード」で回答する。iOS／Androidネイティブ版は対象外。

> 2026-10-18時点：主要画面を本番API（`https://meelyze-api.vercel.app/api/v1`）へ接続済み。登録・ログイン・本人情報／アレルゲンの取得と保存・解析・結果の再取得・店員確認の一括保存をFastAPIで行う。沖縄メニューのプレビュー（`?demo=okinawa`）だけは引き続きブラウザ内の仮保存。実API・実機での一連の操作は未検証（後述）。

作業時は [CLAUDE.md](CLAUDE.md) を参照する。要件・API・画面の正本は [要件](../../requirements.md)、[開発・検証](../../docs/development.md)、[画面仕様](../../docs/screens.md)、[API仕様](../../docs/api.md)。本書は現在のモバイル実装と、未結合・未実装の範囲を説明する。

## 技術スタック

| 用途 | 現在の構成 | 備考 |
|---|---|---|
| 言語 | TypeScript 5.9.3 | `tsc --noEmit` で型チェック |
| 実行環境 | Node.js 24系 | `package.json` は `24.x`（Vercelは範囲指定を受け付けないためメジャー指定）、`.nvmrc` は `24` |
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
| 初回ウォークスルー（全ルート共通） | 初回アクセス時のみ4枚の画像と説明を表示。通常は英語、URLの `?lang=ja` でツアーのみ日本語。進む・戻る・スワイプ・スキップに対応し、終了後は元のアクセス先へ。表示済み状態はブラウザに保存 |
| ① `/`、② `/onboarding` | 開始画面、利用規約モーダルと同意導線 |
| ③ `/register` | `POST /auth/register`。成功時に前のアカウントのタブ内データを消してトークンを保存し⑤へ。公開同意はユーザー指示により現状 `true` 固定（画面での選択欄なし。仕様の③とは差分） |
| ④ `/login` | `POST /auth/login` の後に `GET /me/allergens` で保存済みアレルゲンを取得し、⑤の初期選択にして進む |
| ⑤ `/profiles/setup` | アレルゲン29品目から1品目以上を選択（保存済みの選択を初期表示）。補助APIで検証後、`PUT /me/allergens` で保存してからタブ内にも保持 |
| ⑥ `/map` | `Under construction.` の仮画面。店舗確認画面へ進める |
| ⑧ `/places/select` | 引き継がれた店舗候補の確認、またはスキップ。候補を検索・取得する処理は未実装 |
| ⑨ `/capture`、⑩ `/capture/preview` | 撮影・画像選択、画像加工、写真確認、再撮影。`Analyze` で `POST /menus/analyze`。401ではトークンを破棄してログインを案内 |
| ⑪ `/menu?id=<menu_id>`、⑫ 詳細シート | 表示のたびに `GET /menus/{menu_id}`（解析用トークン）で取り直し、`current_answer` の有無で確認済み料理とAI推定の料理を分ける。取得結果でタブ内のキャッシュを更新。410は再撮影を案内 |
| ⑬ `/confirm?id=<menu_id>&dish_id=<dish_id>`、⑭ 同意モーダル | 1料理×選択アレルゲンの4択（含まれる／同じ料理器具を使っている／含まれない／わからない）。全問回答を検証し、⑭の選択で `POST /menus/{menu_id}/confirmations` に回答と店員の公開可否を一括送信。`request_id` は下書きごとに作り、回答を変えない再送では同じIDを使う。成功後「お客様に端末をお返しください」→⑮。記憶済みの店員同意を再利用する処理はユーザー指示により維持（仕様の⑭とは差分） |
| ⑮ `/result?id=<menu_id>&dish_id=<dish_id>` | 確認APIの応答（`answer_label`・AIの候補・`notices`・`is_public`）を表示し、同じメニューの一覧へ戻る。応答がタブにない場合は⑪で取得した `current_answer` を表示（公開状態は表示しない） |
| ⑯ `/profiles`、⑰ `/profiles/edit` | ⑯は `GET /me` のニックネーム・メールを表示。⑰は `PUT /me/allergens` で保存。読み込み履歴（API 16・17）とログアウト画面は未実装 |

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

未ログインで開ける画面は①〜④（`/`・`/onboarding`・`/register`・`/login`）だけ。それ以外のURLへ直接アクセスした場合、`app/_layout.tsx` が確認の間は画面をロゴで覆い、アカウント用トークンがない、またはログイン時の `expires_at` を過ぎていれば `/login` へ置き換える（期限切れのトークンは破棄）。静的HTMLには各画面の中身を出力しない。これは表示の制御であり、認可はAPIがトークンで判定する。

Map・Scan・Profileのフッターは `src/components/BottomNavigation.tsx` に共通化し、`app/_layout.tsx` から `/map`・`/capture`・`/menu`・`/profiles`・`/profiles/edit` に表示する。画面下部に固定し、本文側で72px＋下部セーフエリアを確保する。最大幅は本文と同じ440px。選択中の項目を緑色で示し、初回ツアー中は非表示にする。

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

接続先は [src/api/endpoints.ts](src/api/endpoints.ts) に集約している。ベースURLの既定値は `https://meelyze-api.vercel.app/api/v1`（本番兼用DB `Meelyze-plus` に接続）。`EXPO_PUBLIC_API_BASE_URL` を設定するとビルド時にその値へ置き換わる（ローカルのAPIで書き込みを試す場合など）。

| キー | 呼び出すAPI | 認証 |
|---|---|---|
| `register` / `login` | `POST /auth/register`・`POST /auth/login` | なし |
| `me` | `GET /me` | アカウント用 |
| `myAllergens` / `saveAllergens` | `GET /me/allergens`・`PUT /me/allergens` | アカウント用 |
| `analyzeMenu` | `POST /menus/analyze` | アカウント用（必須） |
| `getMenu` | `GET /menus/{menu_id}` | 解析用 |
| `createConfirmation` | `POST /menus/{menu_id}/confirmations` | 解析用 |
| `getDishDetails` | 将来用の予約欄（APIの契約・パスは未定義） | — |

ブラウザからFastAPIを直接呼ぶため、**FastAPI側の `ALLOWED_ORIGINS` にフロントのオリジンを追加する必要がある**（2026-10-18時点の本番は `http://localhost:8081` のみ許可）。APIのレート制限はIP単位のため、Expoサーバーを経由する中継にはしない。

リクエストは `src/api/client.ts` の `requestJson` で送り、APIの共通エラー形式を `ApiError` に変換する。アカウント用トークンで401が返った場合は `clearAccountSession` でタブ内のトークン・本人情報を消し、ログインを案内する（アレルゲン選択は残す）。

### 環境変数

| 名前 | 現在の扱い |
|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | 任意。`/api/v1` を含むFastAPIのURL。未設定なら本番APIを使う |
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
- 店員確認は `dietary_answers: []`（食事制限はモバイル画面から除外中）で送る。410（期限切れ）・`confirmation_limit_reached` は再撮影、409は新しい `request_id` で選び直し、通信失敗は同じ内容・IDでの再送を⑭で案内する。
- AI候補の判定、過去回答の集計・時間による重み・スコア、注意フラグの計算はFastAPI側の担当。Expo側の `summary.ts` は返り値を表示用に整形し、AIと履歴を合成した予測値は計算しない。
- 現在の一覧は `current_answer` の有無で区画を分け、AIまたは店員回答のバッジと `notices` による再確認案内を表示する。詳細はAIの説明・根拠と今回の店員回答を表示する。`store_history` の件数・日時・スコアを表示するUIは未実装。
- 原材料候補は現行APIの返却欄がないため、詳細の `likelyIngredients` は空配列。未提供であることと店員への確認案内を表示する。

AIの推定と店員の回答は区別する。「安全」「食べられる」と断定せず、`unknown` や履歴なしを不使用と解釈しない。画像・トークン・個人情報・アレルゲン選択をログへ記録しない。

## プレビューと端末内保存

開発サーバー起動後、`/menu?demo=okinawa` を開くと、固定された沖縄メニュー14品を小麦（ID `3`）・豚肉（ID `23`）の対象で表示する。画像解析APIは呼ばない。

料理を選択し、詳細 → `Ask staff` → 4択回答 → 同意 → 結果 → 一覧、の画面を確認できる構成。初期データには店員回答・過去回答はなく、操作で入力した回答だけをタブ内に仮保存する（プレビューだけはAPIを呼ばない）。実際の店舗確認や本番DBへの保存を示すものではない。

| データ | 保存先 |
|---|---|
| 撮影・選択した画像 | `CaptureContext` のメモリ内 |
| 選択アレルゲン、本人表示情報、アカウント用トークン・ID | `sessionStorage` |
| 解析結果・解析用トークン | `sessionStorage`（メニューIDごと。⑪の再取得で更新、ログイン・登録時に消去） |
| 確認APIの応答（⑮・⑪′で共有） | `sessionStorage`（メニューID・料理IDごと。ログイン・登録時に消去） |
| プレビューの仮の店員回答・回答日時・同意 | `sessionStorage`（メニューIDごと） |
| 店員同意の記憶 | デモ／アカウントIDなしでは `sessionStorage`、アカウントIDありでは `localStorage` |
| 初回ウォークスルーの表示済み状態 | 初回表示時に `localStorage` の `meelyze.walkthrough.seen` へ `1` を保存。保存不可時はページ内メモリのみ |

実メニューの店員回答は確認APIで保存し、⑮の回答・日時・公開可否はサーバー応答に基づいて表示する。プレビューの仮保存は過去回答の集計や公開データへ反映されない。

## Vercel設定

現在の [vercel.json](vercel.json) は次の設定になっている。

- Root Directory：`apps/mobile`
- Build Command：`expo export -p web`
- Output Directory：`dist/client`
- `api/index.ts` の関数は `runtime` を指定せず、Vercel標準のNodeランタイム（`engines.node` の `24.x`）を使う。`@vercel/node@5.1.8` 等の旧版を固定すると、Node 24を知らないため `BUILD_UTILS_NODE_VERSION_INVALID` でビルドが失敗する（2026-10-18に確認）
- 全リクエストを `/api/index` へ渡し、[api/index.ts](api/index.ts) の `expo-server/adapter/vercel` が `dist/server` を使って処理

単に静的ファイルを置くSPA構成ではなく、入力検証・表示整形のAPI Routesも必要になる。デプロイ時は各画面の直接アクセスに加え、上記の補助APIが応答することを確認する。

デプロイ手順：

1. Vercelで新規プロジェクトを作り、Root Directoryを `apps/mobile` にする（Build・Output・Functionsは `vercel.json` の設定を使う。NodeはpackageのenginesでNode 24）。
2. 環境変数は不要（本番APIが既定）。別のAPIを使う場合だけ `EXPO_PUBLIC_API_BASE_URL` を設定して再ビルドする。
3. 発行されたオリジン（例 `https://<project>.vercel.app`、独自ドメインも）をAPIプロジェクトの `ALLOWED_ORIGINS`（カンマ区切り）に追加し、APIを再デプロイする。
4. `curl -s -o /dev/null -w '%{http_code} %header{access-control-allow-origin}\n' -X OPTIONS https://meelyze-api.vercel.app/api/v1/menus/analyze -H "Origin: <フロントのオリジン>" -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: authorization'` が200とオリジンを返すことを確認する。

## 検証と残作業

2026-10-18のAPI結合時に、`npm run typecheck`・`npm run build:web` の成功、`npx expo serve` での全画面・補助APIの応答、本番APIへの書き込みを伴わない確認（マスタ29件、アカウント用・解析用の各リクエストに対するCORSプリフライト、不正トークンへの401・404の形式）を行った。登録・ログイン・解析・店員確認の実送信、ブラウザ実機・Vercel上での動作は未検証。

結合・公開前に次を確認する。

- `npm ci`、`npm run typecheck`、`npm run build:web` の成功。
- スマートフォンでの撮影、カメラ権限拒否時の画像選択、写真確認・再撮影。
- 実APIによる登録・ログイン・本人設定保存・解析・結果再取得（本番兼用DBに書き込むため、試験はローカルのAPI・Supabaseを `EXPO_PUBLIC_API_BASE_URL` で指定して行う）。タイムアウト・期限切れ・失敗時に自動再送しないこと。
- 店員回答の一括保存、同意・公開条件、明示的な「わからない」、再送（同じ `request_id` で200・`replayed=true`）、保存後の⑪′・⑮への反映。
- 店舗検索・位置情報・地図、過去回答の件数／日時表示、本人履歴などの未実装範囲。

食事制限・ゲスト利用・複数人プロファイルを含む全体要件の達成状況は、現行モバイル方針との差分を整理したうえで判断する。
