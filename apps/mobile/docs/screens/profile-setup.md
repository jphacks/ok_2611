# プロファイル設定

- 実装: [`app/profiles/setup.tsx`](../../app/profiles/setup.tsx)
- 入口: 新規登録・ログイン。
- 元画面: 旧Meelyzeの [AllergenDietaryRestrictionView](https://github.com/naga-T28/Meelyze/blob/main/Meelyze/Views/AllergenDietaryRestrictionView.swift)。今回はアレルゲンの表示義務9品目・推奨20品目だけをチップで複数選択する。食事制限4種の欄と説明文は表示しない。
- 選択肢: [`src/content/preferences.ts`](../../src/content/preferences.ts) に今回の [`docs/database.md`](../../../../docs/database.md) と同じアレルゲン29品目を置く。
- 保存: `Save profile` は Expo Router の `POST /profiles/validate` に選択IDを送り、サーバーが既知IDを重複なく1品目以上と判定する。空選択・未知ID・重複は422を返す。外部保存URLが空欄の間は保存せず、検証成功後に仮の `/map` 画面へ進む。URL設定後は保存済みのアカウント用トークンを使い、[`src/api/allergens.ts`](../../src/api/allergens.ts) から `PUT /me/allergens` に送って成功した場合だけ進む。ボタン下の説明文と戻るボタンは表示しない。
- サーバー側の検証: [`app/profiles/validate+api.ts`](../../app/profiles/validate+api.ts) が担当。現行のFastAPI `PUT /me/allergens` は空配列を許可したままなので、直接FastAPIへ送る操作までは拒否できない。実際の保存を接続する際はこのルートを通す設計とし、FastAPI側も同じ条件に変更する必要がある。
- `created=1` のときだけ登録成功の表示を出す。次のマップ画面は現在作成中の仮ページ。
