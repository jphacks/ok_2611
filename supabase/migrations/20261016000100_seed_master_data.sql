-- 固定マスタ：アレルゲン29種（特定原材料9＋準ずるもの20）・食事制限4種。
-- 正本は docs/database.md の「アレルゲンマスタ」「食事制限マスタ」。
-- IDはAPI・VLMと共有する固定値で、表示順（display_order）とは別に管理する。ID 1〜10は既存の値を維持する。
-- 必須データのため seed.sql ではなくマイグレーションで全環境へ同じ値を適用する。

insert into public.allergens (id, code, name, name_en, category, display_order) values
  -- 特定原材料（表示義務：9品目）
  (1,  'egg',           '卵',                   'Egg',            'required',    1),
  (2,  'milk',          '乳',                   'Milk',           'required',    2),
  (3,  'wheat',         '小麦',                 'Wheat',          'required',    3),
  (6,  'buckwheat',     'そば',                 'Buckwheat',      'required',    4),
  (7,  'peanut',        '落花生（ピーナッツ）', 'Peanut',         'required',    5),
  (4,  'shrimp',        'えび',                 'Shrimp',         'required',    6),
  (5,  'crab',          'かに',                 'Crab',           'required',    7),
  (8,  'walnut',        'くるみ',               'Walnut',         'required',    8),
  (11, 'cashew',        'カシューナッツ',       'Cashew',         'required',    9),
  -- 特定原材料に準ずるもの（表示推奨：20品目）
  (12, 'almond',        'アーモンド',           'Almond',         'recommended', 10),
  (13, 'abalone',       'あわび',               'Abalone',        'recommended', 11),
  (14, 'squid',         'いか',                 'Squid',          'recommended', 12),
  (15, 'salmon_roe',    'いくら',               'Salmon roe',     'recommended', 13),
  (16, 'orange',        'オレンジ',             'Orange',         'recommended', 14),
  (17, 'kiwi',          'キウイフルーツ',       'Kiwi',           'recommended', 15),
  (18, 'beef',          '牛肉',                 'Beef',           'recommended', 16),
  (10, 'sesame',        'ごま',                 'Sesame',         'recommended', 17),
  (19, 'salmon',        'さけ',                 'Salmon',         'recommended', 18),
  (20, 'mackerel',      'さば',                 'Mackerel',       'recommended', 19),
  (9,  'soy',           '大豆',                 'Soy',            'recommended', 20),
  (21, 'chicken',       '鶏肉',                 'Chicken',        'recommended', 21),
  (22, 'banana',        'バナナ',               'Banana',         'recommended', 22),
  (23, 'pork',          '豚肉',                 'Pork',           'recommended', 23),
  (24, 'pistachio',     'ピスタチオ',           'Pistachio',      'recommended', 24),
  (25, 'macadamia_nut', 'マカダミアナッツ',     'Macadamia nut',  'recommended', 25),
  (26, 'peach',         'もも',                 'Peach',          'recommended', 26),
  (27, 'yam',           'やまいも',             'Yam',            'recommended', 27),
  (28, 'apple',         'りんご',               'Apple',          'recommended', 28),
  (29, 'gelatin',       'ゼラチン',             'Gelatin',        'recommended', 29);

-- 明示IDで投入したため、identity の次の値を既存IDの後ろへ進める。
alter table public.allergens alter column id restart with 30;

-- 食事制限はアレルゲンとは別のID空間。
insert into public.dietary_restrictions (id, code, name, name_en) values
  (1, 'vegan',      'ヴィーガン',       'Vegan'),
  (2, 'vegetarian', 'ベジタリアン',     'Vegetarian'),
  (3, 'halal',      'ハラール',         'Halal'),
  (4, 'no_alcohol', 'アルコール不使用', 'No alcohol');
