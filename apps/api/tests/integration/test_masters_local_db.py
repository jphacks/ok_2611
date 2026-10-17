"""ローカルSupabase（supabase start）のマスタを、APIを通して読み取る。

接続先はローカルに限る。本番兼用の Meelyze-plus には向けない（読み取りのみだが誤設定を防ぐ）。
  LOCAL_SUPABASE_URL=http://127.0.0.1:54321 LOCAL_SUPABASE_SECRET_KEY=<sb status の SECRET_KEY> python -m pytest -m local_db
"""

import os
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ALLERGEN_ROWS, DIETARY_ROWS

pytestmark = pytest.mark.local_db

URL = os.environ.get("LOCAL_SUPABASE_URL")
KEY = os.environ.get("LOCAL_SUPABASE_SECRET_KEY")


@pytest.fixture(scope="module")
def client() -> TestClient:
    if not URL or not KEY:
        pytest.skip("LOCAL_SUPABASE_URL / LOCAL_SUPABASE_SECRET_KEY が未設定")
    if urlsplit(URL).hostname not in ("127.0.0.1", "localhost"):
        pytest.fail("ローカルSupabase以外には接続しない")
    settings = Settings(_env_file=None, supabase_url=URL, supabase_secret_key=KEY)
    return TestClient(create_app(settings))


def test_allergens_from_local_db(client):
    response = client.get("/api/v1/allergens?locale=en")
    assert response.status_code == 200
    expected = [{**row, "display_name": row["name_en"]} for row in ALLERGEN_ROWS]
    assert response.json() == {"allergens": expected}


def test_dietary_restrictions_from_local_db(client):
    response = client.get("/api/v1/dietary-restrictions")
    assert response.status_code == 200
    expected = [
        {"id": r["id"], "code": r["code"], "name": r["name"], "display_name": r["name_en"]}
        for r in DIETARY_ROWS
    ]
    assert response.json() == {"dietary_restrictions": expected}


def test_invalid_locale_is_rejected_before_db(client):
    response = client.get("/api/v1/allergens?locale=ja")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
