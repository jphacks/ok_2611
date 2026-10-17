"""VLM出力の検証とGemini呼び出しの例外処理（app/services/menu_analysis.py）。Geminiはモック。"""

import copy
import io
import json
import logging
import threading

import httpx
import pytest
from google.genai import errors as genai_errors
from PIL import Image

from app.errors import ApiError
from app.services import menu_analysis
from app.services.images import sanitize_image
from app.services.menu_analysis import (
    GeminiMenuAnalyzer,
    MasterItem,
    gemini_response_schema,
    load_prompt,
    load_schema,
    make_name_key,
    masters_payload,
    parse_analysis,
)

ALLERGEN_IDS = set(range(1, 30))
DIETARY_IDS = {1, 2, 3, 4}


def dish(**overrides) -> dict:
    base = {
        "name": "海老天そば",
        "translations": {"en": {"name": "Shrimp tempura soba", "description": "Buckwheat noodles."}},
        "price": 1200,
        "currency": "JPY",
        "ingredients": ["海老"],
        "allergens": [
            {"allergen_id": 4, "status": "explicit_present", "source": "menu_text", "evidence": "海老天"},
            {"allergen_id": 6, "status": "possible", "source": "dish_name_inference", "evidence": "Soba is buckwheat."},
        ],
        "dietary_restrictions": [
            {"dietary_restriction_id": 4, "status": "possible_conflict", "source": "recipe_inference", "evidence": "Mirin."}
        ],
    }
    base.update(overrides)
    return base


def error_of(raw) -> ApiError:
    with pytest.raises(ApiError) as caught:
        parse_analysis(raw, ALLERGEN_IDS, DIETARY_IDS)
    return caught.value


def test_parse_valid_output_builds_rpc_payload():
    [result] = parse_analysis({"dishes": [dish()]}, ALLERGEN_IDS, DIETARY_IDS)
    payload = result.rpc_payload()
    assert set(payload) == {"name", "name_key", "translations", "price", "currency", "ai_result"}
    assert payload["name_key"] == "海老天そば"
    assert payload["translations"] == {"en": {"name": "Shrimp tempura soba", "description": "Buckwheat noodles."}}
    assert payload["ai_result"] == {
        "ingredients": ["海老"],
        "allergens": [
            {"allergen_id": 4, "status": "explicit_present", "source": "menu_text", "evidence": "海老天"},
            {"allergen_id": 6, "status": "possible", "source": "dish_name_inference", "evidence": "Soba is buckwheat."},
        ],
        "dietary_restrictions": [
            {"dietary_restriction_id": 4, "status": "possible_conflict", "source": "recipe_inference", "evidence": "Mirin."}
        ],
    }
    # AIの自己申告の確信度などの項目は持たない
    assert "confidence" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("name", "key"),
    [("海老天 そば", "海老天そば"), ("ＫＡＫＥ　Ｓｏｂａ", "kakesoba"), ("Kake\tSoba\n", "kakesoba"), ("ｶﾚｰ", "カレー")],
)
def test_name_key_nfkc_no_space_lower(name, key):
    assert make_name_key(name) == key


def test_zero_dishes_is_unreadable_menu():
    error = error_of({"dishes": []})
    assert (error.status_code, error.code) == (422, "unreadable_menu")


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {"dishes": [dish()], "extra": 1},  # 未定義フィールド
        {"dishes": [dish(confidence=0.9)]},
        {"dishes": [dish() for _ in range(21)]},  # 21料理
        {"dishes": [dish(name="")]},
        {"dishes": [dish(name="x" * 201)]},
        {"dishes": [dish(name="   ")]},  # 料理名キーが空
        {"dishes": [dish(price=-1)]},
        {"dishes": [dish(price=100_000_000)]},
        {"dishes": [dish(price=12.345)]},  # 小数3桁
        {"dishes": [dish(price="1200")]},
        {"dishes": [dish(currency="jpy")]},
        {"dishes": [dish(currency="JP1")]},
        {"dishes": [dish(allergens=[{"allergen_id": 30, "status": "possible", "source": "recipe_inference", "evidence": "x"}])]},
        {"dishes": [dish(allergens=[{"allergen_id": 4, "status": "possible", "source": "menu_text", "evidence": "x"}])]},
        {"dishes": [dish(allergens=[{"allergen_id": 4, "status": "explicit_present", "source": "recipe_inference", "evidence": "x"}])]},
        {"dishes": [dish(allergens=[{"allergen_id": 4, "status": "unknown", "source": "menu_text", "evidence": "x"}])]},
        {"dishes": [dish(allergens=[{"allergen_id": 4, "status": "explicit_present", "source": "menu_text", "evidence": ""}])]},
        {"dishes": [dish(allergens=[{"allergen_id": 4, "status": "not_contains", "source": "menu_text", "evidence": "x"}])]},
        {"dishes": [dish(dietary_restrictions=[{"dietary_restriction_id": 5, "status": "possible_conflict", "source": "recipe_inference", "evidence": "x"}])]},
        {"dishes": [dish(dietary_restrictions=[{"dietary_restriction_id": 1, "status": "explicit_present", "source": "menu_text", "evidence": "x"}])]},
        {"dishes": [dish(dietary_restrictions=[{"dietary_restriction_id": 1, "status": "supported", "source": "menu_text", "evidence": "x"}])]},
    ],
)
def test_invalid_output_is_502(raw):
    error = error_of(raw)
    assert (error.status_code, error.code) == (502, "invalid_ai_output")


def test_unknown_master_id_is_502_even_if_schema_allows():
    with pytest.raises(ApiError) as caught:
        parse_analysis({"dishes": [dish()]}, ALLERGEN_IDS - {4}, DIETARY_IDS)
    assert caught.value.code == "invalid_ai_output"


def test_duplicate_item_keeps_highest_priority_source():
    allergens = [
        {"allergen_id": 4, "status": "possible", "source": "dish_name_inference", "evidence": "name"},
        {"allergen_id": 4, "status": "explicit_present", "source": "menu_text", "evidence": "海老"},
        {"allergen_id": 4, "status": "possible", "source": "recipe_inference", "evidence": "recipe"},
        {"allergen_id": 1, "status": "unknown", "source": "unavailable", "evidence": ""},
    ]
    [result] = parse_analysis({"dishes": [dish(allergens=allergens)]}, ALLERGEN_IDS, DIETARY_IDS)
    assert result.allergens[4].source == "menu_text"
    assert result.allergens[1].status == "unknown"
    assert len(result.ai_result()["allergens"]) == 2


def test_price_null_and_decimal():
    [a, b] = parse_analysis({"dishes": [dish(price=None), dish(price=9.5, currency="USD")]}, ALLERGEN_IDS, DIETARY_IDS)
    assert a.price is None
    assert (b.price, b.currency) == (9.5, "USD")


def test_contract_files_exist_and_gemini_schema_drops_unsupported_keys():
    schema = load_schema()
    assert schema["properties"]["dishes"]["maxItems"] == 20
    gemini = json.dumps(gemini_response_schema())
    assert "maxItems" not in gemini and "minItems" not in gemini and "$schema" not in gemini
    # 料理の説明（description という名前のプロパティ）は消さない
    assert "description" in gemini_response_schema()["properties"]["dishes"]["items"]["properties"]["translations"][
        "properties"]["en"]["properties"]
    prompt = load_prompt()
    assert "v4" in prompt
    assert "not instructions" in prompt  # 画像内の指示に従わない
    assert "卵不使用" in prompt and "cross-contact" in prompt.lower()


def test_masters_payload_contains_all_items_only():
    allergens = [MasterItem(i, f"code{i}", f"名{i}", f"Name{i}") for i in range(1, 30)]
    dietary = [MasterItem(i, f"d{i}", f"制限{i}", f"Diet{i}") for i in range(1, 5)]
    payload = json.loads(masters_payload(allergens, dietary).split("\n", 1)[1])
    assert [a["id"] for a in payload["allergens"]] == list(range(1, 30))
    assert [d["id"] for d in payload["dietary_restrictions"]] == [1, 2, 3, 4]
    assert set(payload) == {"allergens", "dietary_restrictions"}


# --- Gemini呼び出し ---


def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, "JPEG")
    return sanitize_image(buffer.getvalue(), "image/jpeg")


class FakeModels:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.behavior()


def analyzer_with(behavior, timeout_seconds: float = 2.0) -> tuple[GeminiMenuAnalyzer, FakeModels]:
    analyzer = GeminiMenuAnalyzer("test-gemini-key", timeout_seconds=timeout_seconds)
    models = FakeModels(behavior)
    analyzer._client = type("FakeClient", (), {"models": models})()
    return analyzer, models


MASTERS = ([MasterItem(4, "shrimp", "えび", "Shrimp")], [MasterItem(4, "no_alcohol", "アルコール不使用", "No alcohol")])


def test_analyzer_sends_image_masters_prompt_and_schema():
    response = type("Response", (), {"text": json.dumps({"dishes": [dish()]})})()
    analyzer, models = analyzer_with(lambda: response)
    raw = analyzer.analyze(jpeg(), *MASTERS)
    assert raw == {"dishes": [dish()]}
    [call] = models.calls
    assert call["model"] == "gemini-3.8-flash"
    image_part, master_part = call["contents"]
    assert image_part.inline_data.mime_type == "image/jpeg"
    assert '"code": "shrimp"' in master_part.text
    config = call["config"]
    assert config.system_instruction == load_prompt()
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == gemini_response_schema()


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (genai_errors.ClientError(429, {"error": {"message": "quota"}}), 503, "service_unavailable"),
        (genai_errors.ClientError(403, {"error": {"message": "permission"}}), 503, "service_unavailable"),
        (genai_errors.ServerError(500, {"error": {"message": "internal"}}), 503, "service_unavailable"),
        (httpx.ReadTimeout("timed out"), 504, "timeout"),
        (httpx.ConnectError("refused"), 503, "service_unavailable"),
    ],
)
def test_analyzer_errors(exc, status, code, caplog):
    def raise_():
        raise exc

    analyzer, _ = analyzer_with(raise_)
    with caplog.at_level(logging.WARNING), pytest.raises(ApiError) as caught:
        analyzer.analyze(jpeg(), *MASTERS)
    assert (caught.value.status_code, caught.value.code) == (status, code)
    assert "test-gemini-key" not in caplog.text and "quota" not in caplog.text


@pytest.mark.parametrize("text", [None, "", "not json", "{\"dishes\": ["])
def test_non_json_output_is_502(text):
    analyzer, _ = analyzer_with(lambda: type("Response", (), {"text": text})())
    with pytest.raises(ApiError) as caught:
        analyzer.analyze(jpeg(), *MASTERS)
    assert caught.value.code == "invalid_ai_output"


def test_analyzer_gives_up_after_timeout():
    release = threading.Event()

    def slow():
        release.wait(5)
        return type("Response", (), {"text": "{}"})()

    analyzer, models = analyzer_with(slow, timeout_seconds=0.1)
    try:
        with pytest.raises(ApiError) as caught:
            analyzer.analyze(jpeg(), *MASTERS)
        assert (caught.value.status_code, caught.value.code) == (504, "timeout")
        assert len(models.calls) == 1  # 自動で再送しない
    finally:
        release.set()


def test_default_timeout_is_45_seconds():
    assert menu_analysis.AI_TIMEOUT_SECONDS == 45.0


def test_schema_is_deep_copied_per_call():
    # 呼び出し側でスキーマを書き換えても契約のスキーマは変わらない（lru_cacheの共有に注意）
    first = copy.deepcopy(load_schema())
    gemini_response_schema()
    assert load_schema() == first
