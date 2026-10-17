# 利用開始前の説明

- 実装: [`app/onboarding.tsx`](../../app/onboarding.tsx)
- 役割: 旧Meelyzeの免責・安全注意を引き継ぎ、AI推定の限界、店員確認、安全非保証、店員が利用者の端末で回答する流れを説明する。文面は [`src/content/terms.ts`](../../src/content/terms.ts) で利用規約画面と共有する。
- 同意: [`/terms`](terms.md) へのリンクと必須チェックボックスを表示し、未チェック時は `Get started` を押せない。
- 遷移: 同意後に `/register?termsAccepted=1`。
