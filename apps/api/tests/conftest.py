import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.config import Settings
from app.main import create_app
from app.services.supabase_client import get_supabase_client

FRONT_ORIGIN = "http://localhost:8081"


class KeepAnalysisDescriptions:
    """料理ごとの説明の生成（Gemini）の代わり。全料理を生成できなかった扱いにし、解析時の説明を残す。"""

    def describe(self, dishes, timeout_seconds):
        return [None] * len(dishes)

# supabase/migrations/20261016000100_seed_master_data.sql と同じ値
ALLERGEN_ROWS = [
    {"id": i, "code": c, "name": n, "name_en": e, "category": cat, "display_order": o}
    for (i, c, n, e, cat, o) in [
        (1, "egg", "卵", "Egg", "required", 1),
        (2, "milk", "乳", "Milk", "required", 2),
        (3, "wheat", "小麦", "Wheat", "required", 3),
        (6, "buckwheat", "そば", "Buckwheat", "required", 4),
        (7, "peanut", "落花生（ピーナッツ）", "Peanut", "required", 5),
        (4, "shrimp", "えび", "Shrimp", "required", 6),
        (5, "crab", "かに", "Crab", "required", 7),
        (8, "walnut", "くるみ", "Walnut", "required", 8),
        (11, "cashew", "カシューナッツ", "Cashew", "required", 9),
        (12, "almond", "アーモンド", "Almond", "recommended", 10),
        (13, "abalone", "あわび", "Abalone", "recommended", 11),
        (14, "squid", "いか", "Squid", "recommended", 12),
        (15, "salmon_roe", "いくら", "Salmon roe", "recommended", 13),
        (16, "orange", "オレンジ", "Orange", "recommended", 14),
        (17, "kiwi", "キウイフルーツ", "Kiwi", "recommended", 15),
        (18, "beef", "牛肉", "Beef", "recommended", 16),
        (10, "sesame", "ごま", "Sesame", "recommended", 17),
        (19, "salmon", "さけ", "Salmon", "recommended", 18),
        (20, "mackerel", "さば", "Mackerel", "recommended", 19),
        (9, "soy", "大豆", "Soy", "recommended", 20),
        (21, "chicken", "鶏肉", "Chicken", "recommended", 21),
        (22, "banana", "バナナ", "Banana", "recommended", 22),
        (23, "pork", "豚肉", "Pork", "recommended", 23),
        (24, "pistachio", "ピスタチオ", "Pistachio", "recommended", 24),
        (25, "macadamia_nut", "マカダミアナッツ", "Macadamia nut", "recommended", 25),
        (26, "peach", "もも", "Peach", "recommended", 26),
        (27, "yam", "やまいも", "Yam", "recommended", 27),
        (28, "apple", "りんご", "Apple", "recommended", 28),
        (29, "gelatin", "ゼラチン", "Gelatin", "recommended", 29),
    ]
]

DIETARY_ROWS = [
    {"id": 1, "code": "vegan", "name": "ヴィーガン", "name_en": "Vegan"},
    {"id": 2, "code": "vegetarian", "name": "ベジタリアン", "name_en": "Vegetarian"},
    {"id": 3, "code": "halal", "name": "ハラール", "name_en": "Halal"},
    {"id": 4, "code": "no_alcohol", "name": "アルコール不使用", "name_en": "No alcohol"},
]


class FakeQuery:
    """supabase-py のクエリビルダーのうち、使う部分だけを真似る。"""

    def __init__(self, client: "FakeSupabase", table: str) -> None:
        self.client = client
        self.table = table
        self.calls: list[tuple] = []

    def select(self, columns: str) -> "FakeQuery":
        self.calls.append(("select", columns))
        return self

    def order(self, column: str, *, desc: bool = False) -> "FakeQuery":
        self.calls.append(("order", column, desc))
        return self

    def in_(self, column: str, values) -> "FakeQuery":
        self.calls.append(("in", column, list(values)))
        return self

    def range(self, start: int, end: int) -> "FakeQuery":
        self.calls.append(("range", start, end))
        return self

    def eq(self, column: str, value) -> "FakeQuery":
        self.calls.append(("eq", column, value))
        return self

    def limit(self, count: int) -> "FakeQuery":
        self.calls.append(("range", 0, count - 1))
        return self

    def execute(self):
        if self.client.error is not None:
            raise self.client.error
        rows = list(self.client.tables.get(self.table, []))
        for call in self.calls:
            if call[0] == "in":
                rows = [row for row in rows if row[call[1]] in call[2]]
            if call[0] == "eq":
                rows = [row for row in rows if row[call[1]] == call[2]]
        orders = [call for call in self.calls if call[0] == "order"]
        for _, column, desc in reversed(orders):  # 先に指定した列を優先する安定ソート
            rows.sort(key=lambda row: row[column], reverse=desc)
        for call in self.calls:
            if call[0] == "range":
                rows = rows[call[1] : call[2] + 1]
        return type("Result", (), {"data": rows})()


class FakeSupabase:
    def __init__(self) -> None:
        # 並び順の処理を確認するため、DBの返却順をわざと崩しておく
        self.tables = {
            "allergens": list(reversed(ALLERGEN_ROWS)),
            "dietary_restrictions": list(reversed(DIETARY_ROWS)),
            "published_menus": [],
        }
        self.queries: list[FakeQuery] = []
        self.error: Exception | None = None

    def table(self, name: str) -> FakeQuery:
        query = FakeQuery(self, name)
        self.queries.append(query)
        return query


def make_api_error(code: str, message: str, details: str | None = None) -> APIError:
    return APIError({"code": code, "message": message, "details": details, "hint": None})


@pytest.fixture
def settings() -> Settings:
    # 開発者の .env を読まない
    return Settings(_env_file=None, allowed_origins=FRONT_ORIGIN)


@pytest.fixture
def fake_supabase() -> FakeSupabase:
    return FakeSupabase()


@pytest.fixture
def app(settings, fake_supabase):
    app = create_app(settings)
    app.dependency_overrides[get_supabase_client] = lambda: fake_supabase
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def okinawa_output():
    return json.loads((Path(__file__).parent / "fixtures" / "okinawa_menu_v4.json").read_text())
