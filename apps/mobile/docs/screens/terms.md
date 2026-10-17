# 利用規約と安全上の注意

- 実装: [`app/terms.tsx`](../../app/terms.tsx)
- 入口: 新規登録画面の `Read the Terms of Use and safety notice`。
- 元資料: 旧Meelyzeの [DisclaimerView](https://github.com/naga-T28/Meelyze/blob/main/Meelyze/Views/DisclaimerView.swift) と [SafetyNoticeView](https://github.com/naga-T28/Meelyze/blob/main/Meelyze/Views/Components/SafetyNoticeView.swift)。AI推定の限界、未確認時の不明扱い、店員確認、安全非保証の内容を [`src/content/terms.ts`](../../src/content/terms.ts) にMeelyze+向けの英語でまとめ、②の説明画面と共有する。
- 今回の追加: サーバーによる画像解析、利用者と店員の二重同意による公開、非公開回答の予測への利用を現行仕様に合わせて説明した。
- 注意: 旧アプリにあったのは短い免責説明で、法的な利用規約一式ではない。この画面の文面はMVP用の草案。正式公開前に利用条件とプライバシーポリシーを確定する（[`docs/development.md`](../../../../docs/development.md) の未決事項）。
