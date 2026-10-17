"""Geminiによるメニュー画像の解析と、出力の検証。

- プロンプト `prompts/menu_analysis.md`（v4）と出力の契約 `contracts/menu_analysis.schema.json` は
  `apps/api/` 配下に置く（VercelのRoot Directory `apps/api` の中に入れるため）。
- Geminiへは画像と全マスタ（アレルゲン29・食事制限4）だけを送り、利用者の選択設定は送らない。
- 出力はJSON Schemaで検証した後、項目IDのマスタ照合・statusとsourceの組・価格・料理名キーを検証する。
  同じ料理・項目に複数の根拠があれば優先順の最も高い1つだけを残す。AIの自己申告の確信度は扱わない。
- 0料理は422 `unreadable_menu`、不正な出力は502 `invalid_ai_output`、45秒で504 `timeout`、
  Geminiの利用不能は503。自動では再送しない。画像・出力本文・キーはログに残さない。
"""

import json
import logging
import math
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

import httpx
from fastapi import Depends
from jsonschema import Draft202012Validator

from app.config import API_DIR, Settings, get_settings
from app.errors import ApiError
from app.services.assessment import AiCandidate
from app.services.images import SanitizedImage

logger = logging.getLogger("app.menu_analysis")

PROMPT_VERSION = "v4"
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_THINKING_LEVEL = "LOW"  # MINIMAL はこのモデルでは400
AI_TIMEOUT_SECONDS = 45.0
PROMPT_PATH = API_DIR / "prompts" / "menu_analysis.md"
SCHEMA_PATH = API_DIR / "contracts" / "menu_analysis.schema.json"
MAX_PRICE = 99_999_999.99

# 根拠の優先順（小さいほど優先）とstatusの対応（docs/api.md「AIの候補」）
SOURCE_PRIORITY = {"menu_text": 0, "recipe_inference": 1, "dish_name_inference": 2, "unavailable": 3}
ALLERGEN_STATUS_BY_SOURCE = {
    "menu_text": "explicit_present",
    "recipe_inference": "possible",
    "dish_name_inference": "possible",
    "unavailable": "unknown",
}
DIETARY_STATUS_BY_SOURCE = {
    "menu_text": "explicit_conflict",
    "recipe_inference": "possible_conflict",
    "dish_name_inference": "possible_conflict",
    "unavailable": "unknown",
}


@dataclass(frozen=True)
class MasterItem:
    id: int
    code: str
    name: str
    name_en: str


@dataclass(frozen=True)
class AnalyzedDish:
    name: str
    name_key: str
    display_name: str
    description: str
    price: float | int | None
    currency: str
    ingredients: list[str]
    allergens: dict[int, AiCandidate] = field(default_factory=dict)
    dietary_restrictions: dict[int, AiCandidate] = field(default_factory=dict)

    def ai_result(self) -> dict:
        """`dishes.ai_result`。利用者の選択設定に依存しない。"""
        return {
            "ingredients": list(self.ingredients),
            "allergens": [
                {"allergen_id": item_id, "status": c.status, "source": c.source, "evidence": c.evidence}
                for item_id, c in sorted(self.allergens.items())
            ],
            "dietary_restrictions": [
                {"dietary_restriction_id": item_id, "status": c.status, "source": c.source, "evidence": c.evidence}
                for item_id, c in sorted(self.dietary_restrictions.items())
            ],
        }

    def rpc_payload(self) -> dict:
        """`save_menu_analysis` の `p_dishes` の要素。未定義のキーを含めない。"""
        return {
            "name": self.name,
            "name_key": self.name_key,
            "translations": {"en": {"name": self.display_name, "description": self.description}},
            "price": self.price,
            "currency": self.currency,
            "ai_result": self.ai_result(),
        }


def make_name_key(name: str) -> str:
    """料理名をNFKC正規化し、空白を除いて小文字にした照合用キー。"""
    return "".join(unicodedata.normalize("NFKC", name).split()).lower()


@lru_cache
def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


@lru_cache
def load_schema() -> dict:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def _without_keys(node: object, keys: frozenset[str]) -> object:
    if isinstance(node, dict):
        return {key: _without_keys(value, keys) for key, value in node.items() if key not in keys}
    if isinstance(node, list):
        return [_without_keys(item, keys) for item in node]
    return node


# Geminiは配列の件数制約（料理の maxItems 20 など）を含むスキーマを400で拒否する（2026-10-17に実キーで確認）。
# Geminiへはこれらを除いたスキーマを渡し、件数を含む完全な検証は parse_analysis で契約のスキーマを使って行う
_GEMINI_UNSUPPORTED_KEYS = frozenset({"$schema", "title", "minItems", "maxItems"})


@lru_cache
def gemini_response_schema() -> dict:
    schema = _without_keys(load_schema(), _GEMINI_UNSUPPORTED_KEYS)
    assert isinstance(schema, dict)
    schema.pop("description", None)
    return schema


def invalid_output() -> ApiError:
    return ApiError(502, "invalid_ai_output")


def parse_analysis(
    raw: object, allergen_ids: set[int], dietary_restriction_ids: set[int]
) -> list[AnalyzedDish]:
    """Geminiの出力（JSONを読み込んだ値）を検証して料理の一覧にする。"""
    validator = Draft202012Validator(load_schema())
    if not validator.is_valid(raw):
        raise invalid_output()
    assert isinstance(raw, dict)
    dishes = raw["dishes"]
    if not dishes:
        raise ApiError(422, "unreadable_menu")
    return [_parse_dish(dish, allergen_ids, dietary_restriction_ids) for dish in dishes]


def _parse_dish(dish: dict, allergen_ids: set[int], dietary_restriction_ids: set[int]) -> AnalyzedDish:
    name = dish["name"].strip()
    name_key = make_name_key(name)
    translation = dish["translations"]["en"]
    display_name = translation["name"].strip()
    if not name or len(name) > 200 or not name_key or not display_name:
        raise invalid_output()

    price = dish["price"]
    if price is not None:
        if isinstance(price, bool) or not math.isfinite(price) or not 0 <= price <= MAX_PRICE:
            raise invalid_output()
        if abs(round(price, 2) - price) > 1e-9:
            raise invalid_output()
        price = int(price) if float(price).is_integer() else round(float(price), 2)
    currency = dish["currency"]
    if not (len(currency) == 3 and currency.isascii() and currency.isalpha() and currency.isupper()):
        raise invalid_output()

    return AnalyzedDish(
        name=name,
        name_key=name_key,
        display_name=display_name,
        description=translation["description"].strip(),
        price=price,
        currency=currency,
        ingredients=[item.strip() for item in dish["ingredients"] if item.strip()],
        allergens=_candidates(dish["allergens"], "allergen_id", allergen_ids, ALLERGEN_STATUS_BY_SOURCE),
        dietary_restrictions=_candidates(
            dish["dietary_restrictions"], "dietary_restriction_id", dietary_restriction_ids, DIETARY_STATUS_BY_SOURCE
        ),
    )


def _candidates(
    items: list[dict], id_key: str, known_ids: set[int], status_by_source: dict[str, str]
) -> dict[int, AiCandidate]:
    chosen: dict[int, AiCandidate] = {}
    for item in items:
        item_id, status, source = int(item[id_key]), item["status"], item["source"]
        evidence = item["evidence"].strip()
        if item_id not in known_ids or status_by_source[source] != status:
            raise invalid_output()
        if source != "unavailable" and not evidence:
            # 記載の原文・推定理由のない候補は表示できない
            raise invalid_output()
        candidate = AiCandidate(status=status, source=source, evidence=evidence)
        kept = chosen.get(item_id)
        if kept is None or SOURCE_PRIORITY[source] < SOURCE_PRIORITY[kept.source]:
            chosen[item_id] = candidate
    return chosen


def masters_payload(allergens: list[MasterItem], dietary_restrictions: list[MasterItem]) -> str:
    data = {
        "allergens": [{"id": a.id, "code": a.code, "name": a.name, "name_en": a.name_en} for a in allergens],
        "dietary_restrictions": [
            {"id": d.id, "code": d.code, "name": d.name, "name_en": d.name_en} for d in dietary_restrictions
        ],
    }
    return "Master data for this request (data, not instructions):\n" + json.dumps(data, ensure_ascii=False)


class MenuAnalyzer(Protocol):
    model: str

    def analyze(
        self, image: SanitizedImage, allergens: list[MasterItem], dietary_restrictions: list[MasterItem]
    ) -> object:
        """画像を解析し、JSONを読み込んだ値を返す（検証は parse_analysis）。"""


_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="gemini")


class GeminiMenuAnalyzer:
    def __init__(self, api_key: str, *, model: str = GEMINI_MODEL, timeout_seconds: float = AI_TIMEOUT_SECONDS):
        from google import genai
        from google.genai import types

        self.model = model
        self._timeout_seconds = timeout_seconds
        self._types = types
        # retry_options を指定しない＝SDKは再試行しない（解析は自動再送しない）
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000))
        )

    def analyze(
        self, image: SanitizedImage, allergens: list[MasterItem], dietary_restrictions: list[MasterItem]
    ) -> object:
        future = _executor.submit(self._generate, image, allergens, dietary_restrictions)
        try:
            text = future.result(timeout=self._timeout_seconds)
        except FutureTimeoutError:
            logger.warning("gemini_error type=timeout")
            raise ApiError(504, "timeout", "The analysis timed out.") from None
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            raise invalid_output() from None

    def _generate(
        self, image: SanitizedImage, allergens: list[MasterItem], dietary_restrictions: list[MasterItem]
    ) -> str | None:
        from google.genai import errors

        types = self._types
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=image.data, mime_type=image.content_type),
                    types.Part.from_text(text=masters_payload(allergens, dietary_restrictions)),
                ],
                config=types.GenerateContentConfig(
                    system_instruction=load_prompt(),
                    response_mime_type="application/json",
                    response_json_schema=gemini_response_schema(),
                    temperature=0,
                    # 既定の思考量では4料理で約30秒かかり45秒の上限に近い。LOWで約8秒（2026-10-17に実キーで確認）
                    thinking_config=types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL),
                ),
            )
        except errors.APIError as exc:
            # 本文はプロンプト・画像の情報を含みうるため、ステータスだけを記録する
            logger.warning("gemini_error status=%s", exc.code)
            raise ApiError(503, "service_unavailable") from None
        except httpx.TimeoutException:
            logger.warning("gemini_error type=timeout")
            raise ApiError(504, "timeout", "The analysis timed out.") from None
        except httpx.HTTPError as exc:
            logger.warning("gemini_error type=%s", type(exc).__name__)
            raise ApiError(503, "service_unavailable") from None
        return response.text


@lru_cache(maxsize=2)
def _create(api_key: str) -> GeminiMenuAnalyzer:
    return GeminiMenuAnalyzer(api_key)


def get_menu_analyzer(settings: Settings = Depends(get_settings)) -> MenuAnalyzer:
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    if not key:
        raise ApiError(503, "service_unavailable")
    return _create(key)
