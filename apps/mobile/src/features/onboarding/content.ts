export type WalkthroughLanguage = "en" | "ja";

type WalkthroughCopy = {
  skip: string;
  skipLabel: string;
  back: string;
  next: string;
  finish: string;
  progressLabel: string;
  progressValue: (current: number, total: number) => string;
  steps: { title: string; description: string; imageLabel: string }[];
};

export const walkthroughContent: Record<WalkthroughLanguage, WalkthroughCopy> = {
  en: {
    skip: "Skip",
    skipLabel: "Skip introduction",
    back: "Back",
    next: "Continue",
    finish: "Get started",
    progressLabel: "Introduction progress",
    progressValue: (current, total) => `Step ${current} of ${total}`,
    steps: [
      {
        title: "Curious about the food.\nUnsure what's inside?",
        description: "Japanese menus can be hard to navigate with food allergies. Meelyze+ helps you find what to ask before you order.",
        imageLabel: "A traveler reading a menu and wondering about shrimp, peanuts, and wheat.",
      },
      {
        title: "One photo.\nA clearer menu.",
        description: "Scan a menu to see English descriptions and possible allergen clues. AI estimates are a starting point: always confirm with staff.",
        imageLabel: "A traveler scanning a menu to review possible allergens for each dish.",
      },
      {
        title: "Your questions.\nIn Japanese.",
        description: "Show your phone to a staff member. They can answer simple questions in Japanese about ingredients and shared cooking utensils.",
        imageLabel: "A traveler showing allergen questions on their phone to restaurant staff.",
      },
      {
        title: "Help the next\ntraveler, too.",
        description: "When you and the staff agree to share, answers for a selected restaurant can help future travelers know what to ask.",
        imageLabel: "Restaurant answers contributing information for the next traveler.",
      },
    ],
  },
  ja: {
    skip: "スキップ",
    skipLabel: "使い方の紹介をスキップ",
    back: "戻る",
    next: "次へ",
    finish: "はじめる",
    progressLabel: "使い方の紹介の進み具合",
    progressValue: (current, total) => `全${total}ステップ中${current}ステップ目`,
    steps: [
      {
        title: "食べてみたい。\nでも、食材が気になる。",
        description: "食物アレルギーがあると、日本語のメニューだけでは食材がわからないことも。Meelyze+が、注文前に確認したいことを見つけるお手伝いをします。",
        imageLabel: "メニューを見ながら、えび・落花生・小麦が含まれるか気にしている旅行者。",
      },
      {
        title: "写真を撮って、\nメニューを読み解く。",
        description: "メニューを撮影すると、料理の英語での説明や、アレルゲンが含まれる可能性を確認できます。AIの推定は参考情報です。必ず店員に確認しましょう。",
        imageLabel: "メニューを撮影し、料理ごとにアレルゲンの可能性を確認する旅行者。",
      },
      {
        title: "聞きたいことを、\n日本語で店員に。",
        description: "店員にスマートフォンを見せてください。食材や調理器具の共用について、日本語の簡単な質問に答えてもらえます。",
        imageLabel: "スマートフォンに表示したアレルゲンの質問を店員に見せる旅行者。",
      },
      {
        title: "その確認が、\n次の旅行者のヒントに。",
        description: "あなたと店員の両方が共有に同意すると、選択したお店での回答が、次の旅行者が確認したいことを見つける手がかりになります。",
        imageLabel: "お店での回答が共有され、次の旅行者の参考になる様子。",
      },
    ],
  },
};
