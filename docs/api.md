# API仕様

`apps/api`（FastAPI）が提供するAPIの一覧、各APIの内容と使い方、処理ルールを記す。

- 本書を基に作成した `contracts/openapi.yaml` を、実装の `/openapi.json` と一致させる。2026-10-17に全17操作を照合した（`apps/api/scripts/compare_openapi.py`、実際の応答と契約の例を契約のスキーマで検証する `apps/api/tests/test_openapi_contract.py`）。
- 技術スタック・環境設定は [apps/api/README.md](../apps/api/README.md) を参照する。
- VLMのプロンプトv4と出力のJSON Schemaは `apps/api/prompts/menu_analysis.md`・`apps/api/contracts/menu_analysis.schema.json`（VercelのRoot Directory `apps/api` に含めるため、この配下に置く）。APIの実装・検証の結果は [API README](../apps/api/README.md) に記録する。

## 共通

| 項目 | 内容 |
|---|---|
| ベースURL | `{API_ORIGIN}/api/v1`。本書のパスはすべてこの後ろに付く |
| 形式 | JSON（UTF-8）。画像解析だけ `multipart/form-data` |
| 命名 | JSONのキーはsnake_case |
| 日時 | UTCのISO 8601（例 `2026-10-17T03:00:00Z`）。日時・版・公開可否の結果はサーバーが決め、クライアントの申告で確定しない |
| 言語 | `locale` で指定する。`en` のみ（既定値）。料理名の英訳・英語の説明・対象項目名・回答ラベルを返す。MVPで `ja` などを指定した場合は422。⑬・⑭の日本語はフロントの固定辞書を使う |
| 入力 | 未定義のフィールドは422で拒否する |
| 認証 | `Authorization: Bearer <token>`。トークンをURLクエリ・本文に入れない |
| キャッシュ | 解析結果・確認結果・アカウント・周辺検索のレスポンスは `Cache-Control: no-store`。公開メニューもMVPではキャッシュしない |

### トークン

利用者の端末1台で完結するため、トークンは2種類だけ使う。店員用のトークンはない。

| トークン | 発行元 | DBの保存先 | 有効期限 | 操作できる範囲 |
|---|---|---|---|---|
| 解析用 | `POST /menus/analyze` | `menus.analysis_token_hash` | 24時間 | そのメニューの再取得、店員確認の保存 |
| アカウント用（P1） | `POST /auth/register`、`POST /auth/login` | 保存しない（署名付きJWT） | 24時間 | 本人情報・履歴の閲覧、本人設定の取得・更新、新規解析時の所有者と登録時同意の特定 |

- 解析用は、256bit以上の乱数をURL-safeに変換したもの。DBにはSHA-256の小文字16進文字列だけを保存する。
- 生のトークンは発行時のレスポンスでだけ返す。再取得APIでは返さない。
- 2種類のトークンは互いに代用できない。
- `menu_id` などのIDを知っていること、トークンハッシュ、CORSの設定だけで権限を判断しない。

### 外部サービス

| サービス | 呼び出し元 | 用途 |
|---|---|---|
| Google Places API（New） | API（サーバー用キー） | 周辺飲食店の検索、店舗のPlace IDの確認 |
| Google Maps JavaScript API | 画面（ブラウザ用キー、P1） | 地図とピンの表示 |
| Gemini | API | メニュー画像の解析 |

- Googleから取得した店名・座標・住所はDBに保存しない。保存するのはPlace IDだけ。
- Googleのデータを表示する画面には、Googleの帰属表示を付ける。

### エラー

形式は全APIで共通。入力エラーもこの形式にそろえ、内部のSQLや外部APIの秘密情報を返さない。

```json
{"error": {"code": "analysis_expired", "message": "The analysis has expired. Please take a new photo."}}
```

| HTTP | 主な意味 | 主な `code` |
|---|---|---|
| 401 | トークンなし／不正／対象と不一致、ログイン失敗 | `unauthorized`、`invalid_analysis_token`、`invalid_credentials`、`account_token_expired` |
| 404 | 存在しない | `not_found`、`place_not_found` |
| 409 | 同じ `request_id` で違う内容の再送、登録済みメール | `request_id_conflict`、`email_already_registered` |
| 410 | 解析用トークンの期限切れ | `analysis_expired` |
| 413 / 415 | 画像の容量超過／非対応形式 | `image_too_large`、`unsupported_image_type` |
| 422 | 不正入力、回答不足・重複、対象外の料理、読めないメニュー、確認回数の上限 | `validation_error`、`answers_invalid`、`dish_not_in_menu`、`unreadable_menu`、`confirmation_limit_reached`、`invalid_allergen_ids`、`invalid_dietary_restriction_ids` |
| 429 | レート制限（解析、周辺検索、登録、ログイン失敗） | `rate_limited` |
| 502 / 503 / 504 | AI出力の不正／外部サービス利用不能／時間超過 | `invalid_ai_output`、`service_unavailable`、`timeout` |

DB関数のSQLSTATEは次のように変換する：`28000`→401、`P0002`→404、`P0003`→410、`40001`→409、`22023`→422。ただし `P0002` の `account_not_found` は、アカウント用トークンの `sub` に当たるアカウントがないことを示すため、トークン検証の失敗と同じ401 `unauthorized` にする。`accounts.email` の一意制約違反（`23505`）は409 `email_already_registered`。その他の制約違反は、内容に応じて422か409にする。PostgRESTが付けるHTTPステータスはこの対応と一致しないため使わない（[API README](../apps/api/README.md#dbエラーの変換)）。

## API一覧

| # | メソッド・パス | 認証 | 優先度 | 内容 | 主な呼び出し元 |
|---|---|---|---|---|---|
| 1 | `GET /health` | なし | P0 | 稼働確認 | 監視、デプロイ確認 |
| 2 | `GET /allergens` | なし | P0 | アレルゲンのマスタ | ⑤、⑰ |
| 3 | `GET /places/nearby` | なし | P0（地図表示はP1） | 現在地周辺の飲食店（Google） | ⑥マップ／周辺一覧、⑧店舗確認 |
| 4 | `POST /menus/analyze` | 任意のアカウント用 | P0 | メニュー画像の解析・判定 | ⑩撮影確認の Analyze |
| 5 | `GET /menus/{menu_id}` | 解析用 | P0 | 解析・判定結果の再取得 | ⑪／⑪′の一覧 |
| 6 | `POST /menus/{menu_id}/confirmations` | 解析用 | P0 | 店員回答と公開可否の一括保存 | ⑭の同意する／同意しない |
| 7 | `GET /places/{google_place_id}/public-menus` | なし | P1 | 店舗・料理ごとの公開回答の集計 | ⑦ |
| 8 | `POST /auth/register` | なし | P1 | アカウント登録 | ③ |
| 9 | `POST /auth/login` | なし | P1 | ログイン | ④ |
| 10 | `GET /me` | アカウント用 | P1 | 自分のアカウント情報 | ⑯ |
| 11 | `GET /me/allergens` | アカウント用 | P1 | 自分のアレルゲンの取得 | ④成功後、⑤、⑯・⑰ |
| 12 | `PUT /me/allergens` | アカウント用 | P1 | 自分のアレルゲンの置き換え | ⑤、⑰ |
| 13 | `GET /dietary-restrictions` | なし | P0 | 食事制限のマスタ | ⑤、⑰、⑬ |
| 14 | `GET /me/dietary-restrictions` | アカウント用 | P1 | 本人の食事制限の取得 | ④成功後、⑤、⑯・⑰ |
| 15 | `PUT /me/dietary-restrictions` | アカウント用 | P1 | 本人の食事制限の置き換え | ⑤、⑰ |
| 16 | `GET /me/menus` | アカウント用 | P1 | 自分が読み込んだメニュー一覧 | ⑯のMy scans、⑦の本人履歴 |
| 17 | `GET /me/menus/{menu_id}` | アカウント用 | P1 | 自分のメニューとその確認結果の詳細 | 本人履歴の詳細 |

ログアウトAPIは設けない（端末でトークンを破棄する）。店員確認の取消・修正APIも設けない（間違えた場合は新しい確認として保存する）。

画面の呼び出し順は [画面仕様](screens.md) を参照する。

## 各APIの詳細

### 1. `GET /health`

APIが起動しているかを確認する。DBや外部サービスへの接続情報、バージョンの詳細は返さない。

```json
{"status": "ok"}
```

デプロイ後、最初に別端末からこのURLへ直接アクセスし、Vercelのデプロイ保護で止まらないことを確認する。

### 2. `GET /allergens`

確認対象にできるアレルゲンの一覧を返す。⑤の初期設定と⑰の編集で使う。

| クエリ | 必須 | 内容 |
|---|---|---|
| `locale` | 任意 | `en` のみ（MVP） |

```json
{"allergens": [
  {"id": 1, "code": "egg", "name": "卵", "name_en": "Egg", "display_name": "Egg", "category": "required", "display_order": 1},
  {"id": 11, "code": "cashew", "name": "カシューナッツ", "name_en": "Cashew", "display_name": "Cashew", "category": "required", "display_order": 9},
  {"id": 24, "code": "pistachio", "name": "ピスタチオ", "name_en": "Pistachio", "display_name": "Pistachio", "category": "recommended", "display_order": 24}
]}
```

- 上のJSONは3件の抜粋。実際は [アレルゲンマスタ](database.md#allergen-master) の指定29品目すべてを `display_order` 順に返す。`category` は `required`（9品目）／`recommended`（20品目）。既存ID 1〜10は維持する。
- 一覧にない食材は、このMVPでは解析・質問の対象にできない。画面でその旨を伝える。

### 3. `GET /places/nearby`

現在地の周辺にある飲食店を、Google Places API（New）のNearby Searchで取得して返す。P0では⑥の周辺一覧・⑧の店舗確認に、P1では⑥の地図のピンに使う。

| クエリ | 必須 | 内容 |
|---|---|---|
| `lat` / `lng` | 必須 | 緯度（-90〜90）／経度（-180〜180） |
| `radius_m` | 任意 | 50〜1000。既定300 |
| `locale` | 任意 | 店名の表示言語（`en` のみ（MVP）） |

```json
{
  "places": [{
    "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
    "name": "Soba Dining Demo",
    "latitude": 35.6815,
    "longitude": 139.7668,
    "address": "1-1 Marunouchi, Chiyoda City",
    "distance_m": 42,
    "has_public_menus": true,
    "public_menu_count": 2
  }],
  "attribution": "Google Maps"
}
```

- APIがサーバー用キーでGoogleを呼ぶ。飲食店の種別に絞り、最大20件を距離順に返す。
- `distance_m` は、現在地（`lat`・`lng`）から店舗の座標までの大圏距離をAPIが計算し、整数のmに四捨五入したもの。`distance_m` の昇順、同じ距離は `google_place_id` の昇順で並べ、同じPlace IDは1件だけ返す。
- レスポンスは `Cache-Control: no-store`。現在地から導いた結果を中間のキャッシュに残さないため。
- `has_public_menus`・`public_menu_count` は、Place IDでMeelyze+の公開メニューと照合して付ける。非公開の確認の有無は返さない。
- `public_menu_count` は、その店舗で ⑦（API 7）に表示される料理の数。`published_menus` に含まれる、店舗ごとの異なる `name_key` の数で、メニュー（撮影した画像）の数ではない。同じ料理が複数のメニュー・利用者で公開されても1件と数え、表記ゆれのある同じ料理は別に数える。`has_public_menus` は `public_menu_count` が1以上のとき `true`。
- 店名・座標・住所はGoogleからそのつど取得し、DBに保存しない。
- 利用者の座標はログに記録しない。
- 位置情報が拒否された場合、画面はこのAPIを呼ばずにスキップを案内する。
- レート制限：IP単位で30回／分（初期案）。Googleの利用料金に注意する。
- エラー：422（範囲外の座標）、429、503（Googleが利用できない）。

### 4. `POST /menus/analyze`

⑩の Analyze から呼び、画像を解析して料理ごとに利用者のアレルゲン・食事制限の判定（AIの候補・店舗の履歴）を返す。同じ店舗で過去の店員確認があれば、履歴として集計する。

認証は任意のアカウント用Bearer。ヘッダーなしならゲストとして `account_id=NULL`・利用者同意falseで保存する。ヘッダーがあれば署名・期限・typ・アカウントの存在を検証し、無効なら401にする。無効な認証を黙ってゲスト扱いしない。検証した `sub` を保存RPCへ渡す。リクエスト本文の `account_id`・`user_publish_consent` は拒否する。

リクエスト（`multipart/form-data`）：

| フィールド | 必須 | 内容 |
|---|---|---|
| `image` | 必須 | JPEG／PNG、2 MiB以下、2000万画素以下 |
| `google_place_id` | 任意 | `GET /places/nearby` で選んだ店舗。省略すると店舗未選択 |
| `allergen_ids` | 任意 | 利用者のアレルゲンID（選んだプロファイルの和集合）。複数指定。省略するとAIが候補に挙げたアレルゲンを判定の対象にする |
| `dietary_restriction_ids` | 任意 | 利用者の食事制限IDの和集合。複数指定。省略時は食事制限の判定を返さない。DBに保存しない |
| `locale` | 任意 | `en` のみ（MVP） |

レスポンス（201、アレルゲン・食事制限を指定した例）：

```json
{
  "menu_id": "22222222-2222-4222-8222-222222222222",
  "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
  "analysis_token": "<解析用トークン（この応答でだけ返す）>",
  "analysis_expires_at": "2026-10-18T03:00:00Z",
  "ai_model": "gemini-3.8-flash",
  "prompt_version": "v4",
  "analyzed_at": "2026-10-17T03:00:00Z",
  "locale": "en",
  "dishes": [
    {
      "dish_id": "33333333-3333-4333-8333-333333333331",
      "dish_version": 1,
      "name": "海老天そば",
      "display_name": "Shrimp tempura soba",
      "description": "Buckwheat noodles in hot broth topped with shrimp tempura.",
      "price": 1200,
      "currency": "JPY",
      "allergens": [
        {
          "allergen_id": 6,
          "display_name": "Buckwheat",
          "ai": {
            "status": "possible",
            "source": "dish_name_inference",
            "evidence": "Soba noodles are usually made with buckwheat.",
            "weight": null
          },
          "current_answer": null,
          "store_history": null,
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": false,
            "history_conflict": false,
            "history_shared_utensils": false
          }
        },
        {
          "allergen_id": 4,
          "display_name": "Shrimp",
          "ai": {
            "status": "explicit_present",
            "source": "menu_text",
            "evidence": "海老天",
            "weight": null
          },
          "current_answer": null,
          "store_history": {
            "match_basis": "name_key",
            "answer_counts": {
              "contains": 1,
              "shared_utensils": 2,
              "does_not_contain": 3,
              "unknown": 1
            },
            "last_answered_at": {
              "contains": "2026-10-10T05:00:00Z",
              "shared_utensils": "2026-10-12T05:00:00Z",
              "does_not_contain": "2026-10-15T05:00:00Z",
              "unknown": "2026-10-16T05:00:00Z"
            },
            "last_confirmed_at": "2026-10-16T05:00:00Z",
            "alpha": 1.79,
            "beta": 3.512,
            "score": 0.338,
            "has_conflict": true
          },
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": false,
            "history_conflict": true,
            "history_shared_utensils": true
          }
        }
      ],
      "dietary_restrictions": [
        {
          "dietary_restriction_id": 4,
          "display_name": "No alcohol",
          "ai": {
            "status": "possible_conflict",
            "source": "recipe_inference",
            "evidence": "The broth seasoning may use cooking sake.",
            "weight": null
          },
          "current_answer": null,
          "store_history": null,
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": false,
            "history_conflict": false,
            "history_cross_contact": false
          }
        }
      ]
    }
  ]
}
```

処理の順序：

1. 容量、MIME、実際の画像形式、画素数を検証する。EXIFの向きを反映し、不要なメタデータを取り除く。
2. `google_place_id` があれば、Place Details（`id` のみ）で存在を確認する。存在しなければ404 `place_not_found`。
3. Geminiへ、画像とアレルゲン・食事制限のマスタを送る。利用者が選択した設定は送らない。出力を `contracts/menu_analysis.schema.json` で検証する。画像内の文章は入力データとして扱い、そこに書かれた指示には従わない。
4. 未知・重複したアレルゲンID・食事制限ID、無効な価格、20料理超過を拒否する。読めない料理は返さず、0料理なら422 `unreadable_menu`。
5. アレルゲン候補の根拠を、後述の「AIの候補」の規則で正規化する。料理名から照合用のキー（`name_key`）を作る。
6. 店舗があれば、`restaurants` に Place ID を登録する（既にあれば再利用）。
7. 非公開Storageへランダムなパスで画像を保存する。`save_menu_analysis` の1回のRPCで、メニューと全料理を登録する。ログイン中は検証済み所有者IDを渡し、DBから登録時同意を読み取って保存する。DB登録に失敗したら、画像をStorage APIで削除する。
8. 店舗があれば、同じ店舗・同じ `name_key` の過去の店員確認を集め、「判定アルゴリズム」で判定を計算する（保存しない）。
9. 解析用トークンと、`locale` の言語での結果を返す。

- `allergen_ids`・`dietary_restriction_ids` は判定の対象選択にだけ使い、DBに保存しない。未知・重複のIDはそれぞれ422 `invalid_allergen_ids`／`invalid_dietary_restriction_ids`。保存する `ai_result` は利用者に依存しない。
- 料理名の英訳と英語の説明（`translations.en`）を解析時に生成して保存する。説明はAIによる推定であり、画面で「AIによる説明」と明示する。
- 画像のパスやURLは返さない。
- 自動では再送しない。通信が失敗した場合は、利用者の操作でやり直す。
- レート制限：IP単位で5回／分、50回／日（初期案）。
- エラー：401（任意で送ったアカウント認証が不正・期限切れ）、404 `place_not_found`、413、415、422 `unreadable_menu`、429、502 `invalid_ai_output`、503、504。

### 5. `GET /menus/{menu_id}`

解析・判定結果を再取得する。⑪／⑪′の再読み込みやプロファイル切替で使う。VLMは再実行しない。

- 認証：解析用トークン。トークンがこの `menu_id` のものでなければ401、期限切れなら410。

| クエリ | 必須 | 内容 |
|---|---|---|
| `allergen_ids` | 任意 | アレルゲンの判定の対象（カンマ区切り）。省略時はAIの候補 |
| `dietary_restriction_ids` | 任意 | 食事制限の判定の対象（カンマ区切り）。省略時は食事制限の判定なし |
| `locale` | 任意 | `en` のみ（MVP） |

- レスポンス：`POST /menus/analyze` と同じ形式。ただし `analysis_token` は含めない。料理は保存された `position` 順に返す。
- 判定は呼び出すたびに計算し直す。このメニューの店員確認は `current_answer`（料理・項目ごとの最新の回答）に、同じ店舗の新しい確認は `store_history` に反映される。
- 例（`current_answer` あり）：

```json
{
  "menu_id": "22222222-2222-4222-8222-222222222222",
  "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
  "analysis_expires_at": "2026-10-18T03:00:00Z",
  "ai_model": "gemini-3.8-flash",
  "prompt_version": "v4",
  "analyzed_at": "2026-10-17T03:00:00Z",
  "locale": "en",
  "dishes": [
    {
      "dish_id": "33333333-3333-4333-8333-333333333331",
      "dish_version": 1,
      "name": "海老天そば",
      "display_name": "Shrimp tempura soba",
      "description": "Buckwheat noodles in hot broth topped with shrimp tempura.",
      "price": 1200,
      "currency": "JPY",
      "allergens": [
        {
          "allergen_id": 6,
          "display_name": "Buckwheat",
          "ai": {
            "status": "possible",
            "source": "dish_name_inference",
            "evidence": "Soba noodles are usually made with buckwheat.",
            "weight": null
          },
          "current_answer": null,
          "store_history": null,
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": false,
            "history_conflict": false,
            "history_shared_utensils": false
          }
        },
        {
          "allergen_id": 4,
          "display_name": "Shrimp",
          "ai": {
            "status": "explicit_present",
            "source": "menu_text",
            "evidence": "海老天",
            "weight": null
          },
          "current_answer": {
            "answer": "contains",
            "confirmed_at": "2026-10-17T03:10:00Z"
          },
          "store_history": {
            "match_basis": "name_key",
            "answer_counts": {
              "contains": 1,
              "shared_utensils": 2,
              "does_not_contain": 3,
              "unknown": 1
            },
            "last_answered_at": {
              "contains": "2026-10-10T05:00:00Z",
              "shared_utensils": "2026-10-12T05:00:00Z",
              "does_not_contain": "2026-10-15T05:00:00Z",
              "unknown": "2026-10-16T05:00:00Z"
            },
            "last_confirmed_at": "2026-10-16T05:00:00Z",
            "alpha": 1.79,
            "beta": 3.512,
            "score": 0.338,
            "has_conflict": true
          },
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": false,
            "history_conflict": true,
            "history_shared_utensils": true
          }
        }
      ],
      "dietary_restrictions": [
        {
          "dietary_restriction_id": 4,
          "display_name": "No alcohol",
          "ai": {
            "status": "possible_conflict",
            "source": "recipe_inference",
            "evidence": "The broth seasoning may use cooking sake.",
            "weight": null
          },
          "current_answer": null,
          "store_history": null,
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": false,
            "history_conflict": false,
            "history_cross_contact": false
          }
        }
      ]
    }
  ]
}
```

### 6. `POST /menus/{menu_id}/confirmations`

⑬で入力し、店員確認カード終了時（⑭）に店員が選んだ公開可否と全回答を一括保存する。利用者の公開同意は③の登録時に取得済みで、解析時に保存した `menus.user_publish_consent` を参照する。このAPIで利用者の同意を上書きしない。結果は英語で返す。

- 認証：解析用トークン（`menu_id` のもの）

```json
{
  "request_id": "66666666-6666-4666-8666-666666666666",
  "answers": [
    {
      "dish_id": "33333333-3333-4333-8333-333333333331",
      "allergen_id": 4,
      "answer": "contains"
    },
    {
      "dish_id": "33333333-3333-4333-8333-333333333331",
      "allergen_id": 6,
      "answer": "shared_utensils"
    }
  ],
  "dietary_answers": [
    {
      "dish_id": "33333333-3333-4333-8333-333333333331",
      "dietary_restriction_id": 4,
      "answer": "unknown"
    }
  ],
  "publish_consent": true,
  "locale": "en"
}
```

`answer` の値（アレルゲン）。⑬では上から順に並べ、単一選択とする。APIの値とDBの値の対応は「判定アルゴリズム」の表を参照する。旧値（`not_contains`・`cross_contact`）は422 `answers_invalid`。

| APIの値 | カードの表示（日本語） | 結果の表示（英語、`answer_label`） |
|---|---|---|
| `contains` | 含まれる | Contains |
| `shared_utensils` | 同じ料理器具を使っている | Shares cooking utensils (ingredients not confirmed) |
| `does_not_contain` | 含まれない | Not an ingredient (cross-contact not confirmed) |
| `unknown` | わからない | Unknown |

レスポンス（201。同じ内容の再送は200）：

```json
{
  "session_id": "44444444-4444-4444-8444-444444444444",
  "confirmed_at": "2026-10-17T03:10:00Z",
  "publish_consent": true,
  "user_publish_consent": true,
  "is_public": true,
  "replayed": false,
  "results": [
    {
      "dish_id": "33333333-3333-4333-8333-333333333331",
      "display_name": "Shrimp tempura soba",
      "allergens": [
        {
          "allergen_id": 6,
          "display_name": "Buckwheat",
          "answer": "shared_utensils",
          "answer_label": "Shares cooking utensils (ingredients not confirmed)",
          "ai": {
            "status": "possible",
            "source": "dish_name_inference",
            "evidence": "Soba noodles are usually made with buckwheat.",
            "weight": null
          },
          "store_history": null,
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": false,
            "history_conflict": false,
            "history_shared_utensils": false
          }
        },
        {
          "allergen_id": 4,
          "display_name": "Shrimp",
          "answer": "contains",
          "answer_label": "Contains",
          "ai": {
            "status": "explicit_present",
            "source": "menu_text",
            "evidence": "海老天",
            "weight": null
          },
          "store_history": {
            "match_basis": "name_key",
            "answer_counts": {
              "contains": 1,
              "shared_utensils": 2,
              "does_not_contain": 3,
              "unknown": 1
            },
            "last_answered_at": {
              "contains": "2026-10-10T05:00:00Z",
              "shared_utensils": "2026-10-12T05:00:00Z",
              "does_not_contain": "2026-10-15T05:00:00Z",
              "unknown": "2026-10-16T05:00:00Z"
            },
            "last_confirmed_at": "2026-10-16T05:00:00Z",
            "alpha": 1.79,
            "beta": 3.512,
            "score": 0.338,
            "has_conflict": true
          },
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": false,
            "history_conflict": true,
            "history_shared_utensils": true
          }
        }
      ],
      "dietary_restrictions": [
        {
          "dietary_restriction_id": 4,
          "display_name": "No alcohol",
          "answer": "unknown",
          "answer_label": "Unknown",
          "ai": {
            "status": "possible_conflict",
            "source": "recipe_inference",
            "evidence": "The broth seasoning may use cooking sake.",
            "weight": null
          },
          "store_history": null,
          "notices": {
            "ai_staff_mismatch": false,
            "recheck_current_answer": true,
            "history_conflict": false,
            "history_cross_contact": false
          }
        }
      ]
    }
  ]
}
```

- `request_id` は、店員確認カードを開いたときに画面が作るUUID。通信が切れて再送した場合の二重保存を防ぐ。
- `answers` はアレルゲン、`dietary_answers` は食事制限の回答配列。両フィールドは必須だが、対象がない側は空配列にできる。合計1〜50回答、料理の和集合は1〜10件。両方空、重複、未知のID・回答値は422 `answers_invalid`。メニューにない料理は422 `dish_not_in_menu`。
- ⑬では選択料理×対象項目の全組にちょうど1回答を求める。APIも各配列の料理集合と項目集合の直積が揃っていることを検証し、両配列が空でない場合は料理集合の一致も検証する。`unknown` は有効な明示回答、欠落・nullは未回答として拒否する。利用者の設定自体はDBに保持しないため、APIは未送信の設定までは復元しない。
- APIはトークンをハッシュ化し、`complete_confirmation_session(menu_id, analysis_token_hash, request_id, answers, dietary_answers, publish_consent)` を1回だけ呼ぶ。確認の作成と回答の保存を分けて呼ばない。
- `confirmed_at` はサーバー時刻。`publish_consent` は今回の店員の選択、`user_publish_consent` は解析時に保存した利用者の選択。`is_public` は両方trueかつ店舗ありの場合だけtrue。ゲストは店員が同意してもfalse。今回の確認の公開状態を返し、同じメニューの別の確認の同意で今回の回答を公開しない。
- 公開可否が「いいえ」でも回答は保存し、同じ店舗の今後の判定（履歴の集計）に使う。店舗未選択の場合は保存するが、履歴にも公開にも使わない。
- `results` は回答した料理だけをメニューの順に返し、各項目に今回の回答（`answer`・`answer_label`）・AIの候補（`ai`）・保存後の履歴の集計（`store_history`、今回の回答を含む）・`notices` を付ける。
- 新規確認は1メニュー5回まで（初期案）。既存の同一内容の再送は上限に数えず、上限到達後も200で返す。新規の6回目は422 `confirmation_limit_reached`。

| 状況 | 結果 |
|---|---|
| 初回の成功 | 201、`replayed=false` |
| 同じ `request_id` で同じ内容を再送 | 200、`replayed=true`。行は増えない |
| 同じ `request_id` で違う内容を送信 | 409 `request_id_conflict` |
| 解析用トークンの期限切れ | 410 `analysis_expired` |

<a id="public-menus"></a>

### 7. `GET /places/{google_place_id}/public-menus`（P1）

⑦で店舗・正規化料理名ごとに公開データをまとめて返す。他の利用者が読み込んだ同じ店舗・同じ料理の結果も集計する。個別の読み込み履歴は返さない。認証なし。応答は `Cache-Control: no-store`。

| クエリ | 必須 | 内容 |
|---|---|---|
| `allergen_ids` | 任意 | 閲覧者のアレルゲンID（カンマ区切り）。省略時は代表料理のAIの候補。DBには保存しない |
| `dietary_restriction_ids` | 任意 | 食事制限ID（カンマ区切り）。省略時は食事制限の判定なし。DBには保存しない |
| `locale` | 任意 | `en` のみ |

```json
{
  "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
  "match_basis": "name_key",
  "staff_answers_verified": false,
  "dishes": [
    {
      "name_key": "海老天そば",
      "name": "海老天そば",
      "display_name": "Shrimp tempura soba",
      "description": "Buckwheat noodles in hot broth topped with shrimp tempura.",
      "price": 1200,
      "currency": "JPY",
      "allergens": [
        {
          "allergen_id": 4,
          "display_name": "Shrimp",
          "ai": {
            "status": "explicit_present",
            "source": "menu_text",
            "evidence": "海老天",
            "weight": null
          },
          "store_history": {
            "match_basis": "name_key",
            "answer_counts": {
              "contains": 1,
              "shared_utensils": 2,
              "does_not_contain": 3,
              "unknown": 1
            },
            "last_answered_at": {
              "contains": "2026-10-10T05:00:00Z",
              "shared_utensils": "2026-10-12T05:00:00Z",
              "does_not_contain": "2026-10-15T05:00:00Z",
              "unknown": "2026-10-16T05:00:00Z"
            },
            "last_confirmed_at": "2026-10-16T05:00:00Z",
            "alpha": 1.79,
            "beta": 3.512,
            "score": 0.338,
            "has_conflict": true
          },
          "notices": {
            "history_conflict": true,
            "history_shared_utensils": true
          }
        }
      ],
      "dietary_restrictions": []
    }
  ]
}
```

- `published_menus`・`published_confirmation_answers`・`published_dietary_answers` だけを使う。全ビューは店舗あり・利用者同意true・店員同意trueを必要とする。どちらかが不同意の回答の内容・件数は返さない。
- 同じ店舗の `name_key` ごとに1料理とする。名称・訳・説明・価格・AI候補は公開対象のうち撮影日時が最新の料理から採用し、同日時は料理IDの降順で選ぶ。AIの候補は代表料理のものを別に返し、店員回答と合成しない。回答は同じ料理・同じ項目の公開回答を全利用者分、「判定アルゴリズム」と同じ規則で集計する（同じメニューは最新の1件）。
- 公開集計には「今回の回答」はなく、各項目は `ai`・`store_history`・`notices`（`history_conflict`・`history_shared_utensils`／食事制限は `history_cross_contact`）だけを返す。`match_basis="name_key"` は料理名による暫定の照合、`staff_answers_verified=false` は店員の回答が未認証であることを示す。
- `store_history` は集計であり個別履歴ではない。公開APIに所有者ID・`menu_id`・`dish_id`・`session_id`・個別の確認カードを返さない。画像・トークン・本人の選択設定も返さない。
- 回答の不一致は件数・最終日時とともに示す。
- 代表料理の撮影日時の降順、同日時は `name_key` 順で返す。公開対象がなければ `dishes` は空配列。店名・座標は返さず、画面は周辺検索の結果を使う。
- ⑦の個別履歴欄はAPI 16を店舗で絞って別途取得する。公開集計と本人の履歴を混ぜない。

### 8. `POST /auth/register`（P1）

③でアカウントと今後の読み込み結果の公開可否を登録する。利用規約への同意とは区別し、公開に同意しなくても登録できる。

```json
{"email": "traveler@example.com", "nickname": "Alex", "password": "<8〜128文字>", "publish_consent": true}
```

レスポンス（201）：

```json
{
  "account": {"id": "55555555-5555-4555-8555-555555555555", "email": "traveler@example.com", "nickname": "Alex", "publish_consent": true, "publish_consent_recorded_at": "2026-10-17T03:00:00Z", "publish_consent_version": "2026-10-17-v1", "created_at": "2026-10-17T03:00:00Z"},
  "access_token": "<アカウント用トークン>",
  "token_type": "bearer",
  "expires_at": "2026-10-18T03:00:00Z"
}
```

1. `email` は前後の空白を除いて小文字にし、形式と長さ（254文字以内）を検証する。
2. `nickname` は前後の空白を除いて1〜30文字。制御文字は拒否する。重複してもよい。
3. `password` は8〜128文字。前後の空白は削らない。メールアドレスと同じ値は拒否する。
4. `publish_consent` は明示的なbooleanを必須とし、欠落・nullを422で拒否する。falseでも登録できる。同意記録日時はDB、文言バージョンはAPIの `2026-10-17-v1` を使い、クライアントから日時・バージョンを指定させない。パスワードをArgon2idでハッシュ化し、同意の選択と同一トランザクションで `accounts` に登録する。平文はDB・ログ・レスポンスに含めない。
5. メールアドレスの重複は、一意制約の違反で検出して409 `email_already_registered` にする。事前のSELECTだけで判定しない。

- メール確認はP2。重複時の409は登録済みかを第三者が判別できるため、登録にもレート制限を適用する。
- レート制限：IP単位で5回／時（初期案）。

### 9. `POST /auth/login`（P1）

メールアドレスとパスワードでログインする。

```json
{"email": "traveler@example.com", "password": "<パスワード>"}
```

- レスポンス（200）：`POST /auth/register` と同じ形式。
- `email` は登録時と同じ規則で正規化して検索する。
- Argon2idで照合する。アカウントがない場合もダミーのハッシュで照合し、応答時間の差を小さくする。
- 失敗した場合は、メールアドレスとパスワードのどちらが誤りかを区別せず、401 `invalid_credentials` を返す。
- ハッシュのパラメータが現行の設定より弱い場合は、ログイン成功時に再ハッシュして保存する。
- レート制限：失敗はIP単位で10回／分、メールアドレス単位で5回／15分（初期案）。超えたら429。

アカウント用トークンの仕様：

- HS256で署名したJWT。鍵は `AUTH_JWT_SECRET`（APIの環境変数、32バイト以上の乱数）。
- 中身は `sub`（`accounts.id`）、`iat`、`exp`、`typ="account"` だけ。メールアドレス、ニックネーム、アレルゲン・食事制限は含めない。
- 有効期限は24時間。期限切れは401 `account_token_expired`。リフレッシュトークンはない。
- 検証時は署名・`exp`・`typ` を確認し、`sub` のアカウントがDBにあることも確認する。
- DBに保存しないため、サーバー側ではすぐに無効にできない。ログアウトは端末でトークンを破棄して行う。

### 10. `GET /me`（P1）

ログイン中のアカウントの情報を返す。

```json
{"id": "55555555-5555-4555-8555-555555555555", "email": "traveler@example.com", "nickname": "Alex", "publish_consent": true, "publish_consent_recorded_at": "2026-10-17T03:00:00Z", "publish_consent_version": "2026-10-17-v1", "created_at": "2026-10-17T03:00:00Z"}
```

`password_hash` は返さない。

### 11. `GET /me/allergens`（P1）

ログイン中のアカウントが登録したアレルゲンを返す。

```json
{"allergen_ids": [4, 6]}
```

- `allergen_ids` は昇順。未登録は空配列。更新日時は現行のDBに保存する列がないため応答項目にしない。
- 登録がないことは「アレルギーがない」という意味ではない。

### 12. `PUT /me/allergens`（P1）

ログイン中のアカウントのアレルゲンを、指定した内容で全件置き換える。

```json
{"allergen_ids": [4, 6]}
```

- レスポンス（200）：`GET /me/allergens` と同じ形式。
- 空配列も指定できる。重複・未知のIDは422 `invalid_allergen_ids`。
- `replace_account_allergens` の1回のRPCで置き換える。削除と追加を分けて呼ばない。

アカウントAPI（10〜12・14〜17）に共通する扱い：

- 操作対象は常にトークンの `sub` で決める。URLや本文でアカウントIDを受け取らない。
- 画面では、アカウントのアレルゲンを端末内プロファイルの一つ（本人）として扱い、`POST /menus/analyze` の `allergen_ids` に含める。
- ログインは任意。未ログインでもP0（1〜6・13）を全て使える。

### 13. `GET /dietary-restrictions`

選択式の食事制限マスタを返す。クエリは `locale=en` のみ（省略可）。自由入力は受け付けない。

```json
{"dietary_restrictions":[
  {"id":1,"code":"vegan","name":"ヴィーガン","display_name":"Vegan"},
  {"id":2,"code":"vegetarian","name":"ベジタリアン","display_name":"Vegetarian"},
  {"id":3,"code":"halal","name":"ハラール","display_name":"Halal"},
  {"id":4,"code":"no_alcohol","name":"アルコール不使用","display_name":"No alcohol"}
]}
```

### 14. `GET /me/dietary-restrictions`（P1）

アカウント用トークンの本人の設定を返す。

```json
{"dietary_restriction_ids":[1,4]}
```

IDは昇順、未登録は空配列。空配列を「食事制限がないと確認済み」と解釈しない。

### 15. `PUT /me/dietary-restrictions`（P1）

本文は `{"dietary_restriction_ids":[1,4]}`。本人の設定を `replace_account_dietary_restrictions` の1回のRPCで全件置換し、API 14と同じ形式を返す。空配列は許可し、未知・重複のIDは422 `invalid_dietary_restriction_ids`。対象アカウントはトークンの `sub` から決める。

⑤・⑰ではアレルゲンと食事制限を別々に保存する。両方成功後に⑤は⑥へ、⑰は⑯へ進み、片方失敗時は成功済みの内容を保持して失敗側を再試行する。⑰では29品目のアレルゲンと4種の食事制限の両方を編集できる。アカウントIDは本人履歴の所有者としてメニューへ紐づけるが、選択設定をメニューや回答に複製しない。

### 16. `GET /me/menus`（P1）

アカウント用Bearerで、本人がログイン中に解析成功したメニューだけを返す。⑯の `My scans` と⑦の本人履歴に使う。公開メニューの閲覧は履歴へ追加しない。

| クエリ | 必須 | 内容 |
|---|---|---|
| `google_place_id` | 任意 | ⑦ではその店舗の本人履歴だけに絞る。省略時は店舗未選択も含む全履歴 |
| `limit` | 任意 | 既定20、1〜50 |
| `cursor` | 任意 | 前ページの `next_cursor`。作成日時とIDによるページ位置。認証の代わりにしない |
| `locale` | 任意 | `en` のみ |

```json
{
  "menus": [{
    "menu_id": "22222222-2222-4222-8222-222222222222",
    "google_place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
    "scanned_at": "2026-10-17T03:00:00Z",
    "dish_names": ["Shrimp tempura soba"],
    "dish_count": 1,
    "confirmation_count": 1,
    "is_public": true
  }],
  "next_cursor": null
}
```

- DBクエリに必ず `menus.account_id = JWT.sub` を入れる。公開可否に関係なく本人分だけを、`created_at DESC, id DESC` で返す。未確認・非公開・店舗未選択でも履歴に含める。結果なしは空配列。
- `scanned_at` は解析保存日時。`dish_names` は元メニュー順の英語名、`confirmation_count` は当該メニューの確認件数、`is_public` はそのメニューに公開可能な確認が1件以上あるかをサーバーが判定する。
- 所有者条件と店舗条件はANDで適用する。cursorを変更しても別アカウントの履歴は取得できない。不正cursorは422。ページ位置にないことだけでエラーにはしない。
- 画像・画像URL・トークン・所有者ID・選択プロファイルは返さない。利用者同意がfalseでも本人履歴は利用できる。

### 17. `GET /me/menus/{menu_id}`（P1）

本人が読み込んだメニューの詳細をアカウント用Bearerで取得する。`menu_id` と `account_id = JWT.sub` を同じクエリで検証し、他人のメニュー・所有者なし・存在しないIDはすべて404。解析用トークンでは利用できない。

クエリはAPI 5と同じ `allergen_ids`・`dietary_restriction_ids`・`locale`。VLMは再実行せず、選択設定も保存しない。

レスポンスはAPI 5の `menu_id`・`google_place_id`・`ai_model`・`prompt_version`・`analyzed_at`・`locale`・`dishes` と、次の項目で構成する。`analysis_token`・`analysis_expires_at`・画像・所有者情報は返さない。

| 項目 | 内容 |
|---|---|
| `user_publish_consent` | この解析に保存された利用者同意 |
| `is_public` | 当該メニューに公開可能な確認が1件以上あるか |
| `confirmations` | 当該メニューに保存された確認のみ。新しい順（同日時はIDの降順）の `session_id`・`confirmed_at`・店員の `publish_consent`・当該確認の `is_public`・`results`（API 6と同じ料理別回答形式）。未確認なら空配列 |

- `dishes[].allergens[].store_history` と `dishes[].dietary_restrictions[].store_history` は他の人の結果も加味した履歴の集計（`current_answer` はこのメニューの最新の確認）、`confirmations` は本人が読み込んだこのメニューでの個別回答。別の人の読み込みに紐づく確認は、公開されていても `confirmations` に入れない。
- 解析トークンが失効していても本人の履歴閲覧は可能。読み取り専用であり、店員回答を追加する権限や解析用トークンの再発行はしない。
- 画像は原則24時間で削除されるが解析済みテキストと回答は履歴として残す。履歴保持期間・アカウント削除時の扱いは一般公開前に決める。
- ゲストはこのAPIを使わず、現在のタブの解析一覧と保存成功時の結果だけを表示する。登録後にゲスト解析を自動で移管しない。

## 食事制限の回答

確認条件とIDは [食事制限マスタ](database.md#dietary-master) を共用する。API 4・5・7・17の料理には `dietary_restrictions` 配列を返し、未指定なら空配列。API 6の入力は `dietary_answers`、出力は `results[].dietary_restrictions` とする。

| 値（APIとDBで同じ） | ⑬の日本語（この順に並べる） | ⑮の英語（`answer_label`） | 履歴の集計 |
|---|---|---|---|
| `not_supported` | 対応できない | Not supported | α |
| `cross_contact` | 共用器具による交差接触 | Cross-contact | 加算しない（件数・日時だけ） |
| `supported` | 対応している | Supported (staff answer) | β |
| `unknown` | わからない | Unknown | 加算しない（件数・日時だけ） |

アレルゲンとは別ID・別回答配列で扱い、公開条件・再送判定・件数上限は両配列に適用する。`supported` は未認証の店員回答であり、安全性や認証の保証ではない。

## 判定アルゴリズム

`apps/api/app/services/assessment.py` に実装する。料理×確認項目ごとに、次の4つを**別々に**返し、一つの値に合成しない。結果は保存せず、呼び出すたびに計算する。「安全」「食べられる」に当たる値は返さない。

| 項目 | 内容 | API |
|---|---|---|
| `ai` | AIの候補・根拠・根拠の分類ごとの重み | 4・5・6・7・17 |
| `current_answer` | このメニューの今回の店員回答（料理・項目ごとの最新の確認）。未回答は `null` | 4（常に `null`）・5・17。6は `answer`・`answer_label` |
| `store_history` | 同じ店舗の過去の店員回答の集計 | 4・5・6・7・17 |
| `notices` | 表示ルールに使う判定 | 4・5・6・7・17（7は履歴の判定だけ） |

旧方式の `prediction`・`basis`・`vote_shares` とAIの仮の票（`ai_prior`、`AI_PRIOR_WEIGHT_*`）は廃止した（2026-10-17）。

### 判定アルゴリズムの資料との関係

本節を正本とする。基にした資料は `apps/api/docs/algorithms.md`（論文を参考にした実装案。Git管理外の作業資料）で、MVPでは次の点が異なる（2026-10-17にユーザーが決定）。

| 項目 | algorithms.md | 本書（MVP） |
|---|---|---|
| 履歴の数値集計（α・β・S） | 店員認証・重複排除・料理の同一性確認の後に有効化 | MVPから有効にする |
| 履歴の照合範囲 | 店舗・料理・レシピ版が一致するもの。料理名だけでは同一とみなさない | 同じ店舗・`name_key`・項目IDによる暫定の照合（`match_basis="name_key"`）。レシピ版による同一性は未決 |
| 重複の扱い | 同じ確認の再送・転載、同じ回答者・確認資料に由来する回答を重複加算しない | 再送は `request_id` で1件（RPC）。同じメニューへの複数回の確認は最新の1件だけを数える。回答者・確認資料の同一性は判定できない |
| 公開集計 | 店舗関係者と確認できない回答を除外 | 全回答が未認証のため除外できない。`staff_answers_verified=false` で未認証の回答であることを示す |
| 食事制限 | 記載なし | アレルゲンと同じ規則（下表） |
| フィールド名 | `answer_status` | `answer`（DBの列名と同じ） |

### AIの候補

VLMが自己申告する確信度は使わない。各料理×項目の候補に、次のいずれか一つの根拠（`source`）を割り当てる。

| 優先 | `source` | 根拠 | アレルゲンの `status` | 食事制限の `status` |
|---|---|---|---|---|
| 1 | `menu_text` | メニューに含有・抵触の記載がある | `explicit_present` | `explicit_conflict` |
| 2 | `recipe_inference` | 一般的な参照レシピに含まれる（その店舗の実際のレシピではない） | `possible` | `possible_conflict` |
| 3 | `dish_name_inference` | 料理名からの推定 | `possible` | `possible_conflict` |
| — | `unavailable` | 記載なし・判読不能・根拠不足 | `unknown` | `unknown` |

- 同じ料理・項目に複数の根拠がある場合、優先順位の最も高い一つだけを残す。`status` と `source` の組が上表と異なる出力は502 `invalid_ai_output`。
- `menu_text` の `evidence` には対応する原文、推定の `evidence` には推定理由を入れる。「卵不使用」「除去可能」や別の料理の注記を含有の記載にしない。
- 記載がないことを「含まない」と解釈しない。候補がない項目は `unknown`／`unavailable`。AIは交差接触・不使用・食事制限への対応可を判断しない。
- `weight`：根拠の分類ごとの重み `w=(c+1)/(n+2)`（n：その分類で候補を出した検証件数、c：店舗のレシピ・原材料表示で含有を確認できた件数）。検証データがないMVPでは常に `null` とし、根拠の原文・推定理由を表示する。重みが低くても候補を「なし」に変えない。

### 店員回答の値

アレルゲンの4択はAPIとDBで値の名前が異なり、APIで変換する（変換は `apps/api/app/services/answers.py` の1か所。RPCにはDBの値を渡す）。

| 画面の選択肢（⑬の順） | APIの値 | DBの値 | 意味 | 履歴の集計 |
|---|---|---|---|---|
| 含まれる | `contains` | `contains` | 原材料に含まれる | α |
| 同じ料理器具を使っている | `shared_utensils` | `cross_contact` | 対象を使う別の料理と器具を共有している。原材料への含有は未確認 | 加算しない。件数・日時を別に表示 |
| 含まれない | `does_not_contain` | `not_contains` | 原材料に使っていないと確認できる。交差接触がないことは意味しない | β |
| わからない | `unknown` | `unknown` | いずれも確認できない | 加算しない。件数・日時を別に表示 |

- 店員には選択順を案内する：原材料への含有を確認できる→「含まれる」、それ以外で器具共有が分かる→「同じ料理器具を使っている」、それ以外で原材料に使っていないと確認できる→「含まれない」、いずれも確認できない→「わからない」。単一選択のため、選ばれなかった事実を自動で補わない。
- 「同じ料理器具を使っている」の意味は、旧ラベル「原材料ではないが器具を共有」から「含有は不明」に変わった。2026-10-17時点で本番兼用DB（`Meelyze-plus`）に回答はなく、旧ラベルで入力された回答の扱いは不要。
- 食事制限はAPIとDBで同じ値（`not_supported`→α、`supported`→β、`cross_contact`・`unknown` は加算しない）。⑬の順は「対応できない→共用器具による交差接触→対応している→わからない」。
- 未回答はレコードなし（`current_answer: null`）とし、`unknown` と区別する。

### 履歴の範囲

次の条件をすべて満たす回答を使う。

- 同じ店舗（`confirmation_sessions.restaurant_id`）。店舗未選択のメニューの回答は使わず、店舗未選択の解析では `store_history` は常に `null`。
- 同じ料理名キー（`dishes.name_key`）。料理名をNFKCで正規化し、空白を除いて小文字にしたもの。表記ゆれは統合しない。
- 同じ項目ID。アレルゲンと食事制限は混ぜない。
- 解析・再取得・本人履歴（API 4・5・17）と確認の結果（API 6）は公開・非公開の両方を使う。公開集計（API 7）は公開ビューの回答（店舗あり・利用者同意・店員同意）だけを使う。
- 同じメニューへの複数回の確認は、最新の1件だけを数える（同じ日時に同名の料理が2つある場合は⑬の順で先の回答）。このメニュー自身の最新の回答も履歴に含める。
- 範囲内の回答が0件なら `store_history` は `null`。

### 計算式

```text
w_i = 2 ** (-d_i / STORE_ANSWER_HALF_LIFE_DAYS)   # d_i：回答からの経過日数（小数、未来は0）。初期値30日（仮設定）
α = 1 + Σ w_i（含まれる／not_supported）
β = 1 + Σ w_i（含まれない／supported）
S = α / (α + β)                                     # α・βに加算する回答が0件なら null
```

- `store_history` は `match_basis`・4択それぞれの件数（`answer_counts`）と最終日時（`last_answered_at`）・`last_confirmed_at`・`alpha`・`beta`・`score`（S。いずれも小数3桁）・`has_conflict` を返す。
- 例：重みがすべて1で、含まれる1・含まれない3・器具共有2・わからない1なら α=2、β=4、S≈0.333。器具共有と不明は件数だけ。
- 重みは経過0日・30日・60日で1.00・0.50・0.25。半減期は食品情報の有効期限を意味しない。
- `S` は含有・非含有を明示した回答内の「含まれる」の傾向で、全回答に占める割合や含有確率ではない。画面では4択すべての件数・日時を優先して表示する。
- `has_conflict`：α側とβ側の回答が両方ある。器具共有・不明だけでは立てない。

### 表示ルール（`notices`）

| 項目 | 条件 | 画面 |
|---|---|---|
| `ai_staff_mismatch` | AIの `explicit_present`（食事制限は `explicit_conflict`）と、今回の回答 `does_not_contain`（`supported`） | 根拠と回答を併記し、再確認を案内 |
| `recheck_current_answer` | 今回の回答が `unknown` | 「わからない」と再確認の案内 |
| `history_conflict` | 履歴の `has_conflict` | 「過去の回答に不一致あり」と件数・日時 |
| `history_shared_utensils`（食事制限は `history_cross_contact`） | 履歴に器具共有（`cross_contact`）がある | 「過去に器具共有の回答あり」と件数・日時を別表示 |

- AIの含有候補と器具共有の回答は両立するため、食い違いに数えない。推定の候補（`possible`）と「含まれない」も食い違いに数えない。
- 今回の回答の表示：含まれる／含まれない（交差接触は未確認）／器具共有（含有は未確認）／わからない（再確認）／未回答（`null`）。
- 公開集計（API 7）には今回の回答がないため、`notices` は `history_conflict` と器具共有の2項目だけ。

### 制約

- 過去の「含まれない」や低いAIの重みから、自動で「安全」「食べられる」と判定しない。店員確認カードの対象から外さない。
- 判定は保存しない。過去の回答も上書きしない。
- 店員の回答は利用者の端末で入力された未認証のものなので、全回答を同じ重みで扱う。誤った回答や悪意のある回答が混ざる可能性を画面で伝える（件数と日時を必ず表示する）。
- 半減期は仮設定。検証データで評価するまで変えない。
- `supported` でも「対応を保証」「認証済み」と表示しない。
