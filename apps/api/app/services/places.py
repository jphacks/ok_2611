"""Google Places API（New）の呼び出し。

- 周辺検索は Nearby Search（`places:searchNearby`）、存在確認は Place Details（`id` だけのフィールドマスク）。
- サーバー用キー（`GOOGLE_MAPS_SERVER_API_KEY`）はヘッダーで送り、URLに入れない。
- Googleから取得した店名・座標・住所はDBに保存しない。保存してよいのはPlace IDだけ（03）。
- ログにはステータスと例外の型名だけを残す。URL・本文（座標・キーを含みうる）は残さない。
"""

import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

import httpx
from fastapi import Depends

from app.config import Settings, get_settings
from app.errors import ApiError

logger = logging.getLogger("app.places")

PLACES_BASE_URL = "https://places.googleapis.com/v1"
ATTRIBUTION = "Google Maps"
# 飲食店。Table Aの restaurant は、より具体的な種別（ramen_restaurant など）の店舗も返す
RESTAURANT_TYPES = ["restaurant"]
MAX_RESULTS = 20
NEARBY_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.location",
        "places.shortFormattedAddress",
        "places.formattedAddress",
    ]
)
TIMEOUT_SECONDS = 5.0

# Place ID は英数字・`_`・`-` だけ。それ以外はGoogleに送らずに存在しないものとして扱う
_PLACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


@dataclass(frozen=True)
class GooglePlace:
    google_place_id: str
    name: str
    latitude: float
    longitude: float
    address: str


class PlacesClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._client = httpx.Client(
            base_url=PLACES_BASE_URL,
            headers={"X-Goog-Api-Key": api_key, "Content-Type": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def search_nearby(
        self, latitude: float, longitude: float, radius_m: int, language: str
    ) -> list[GooglePlace]:
        body = {
            "includedTypes": RESTAURANT_TYPES,
            "maxResultCount": MAX_RESULTS,
            "rankPreference": "DISTANCE",
            "languageCode": language,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": float(radius_m),
                }
            },
        }
        response = self._send(
            "POST", "/places:searchNearby", json=body, headers={"X-Goog-FieldMask": NEARBY_FIELD_MASK}
        )
        if response.status_code != 200:
            raise _unavailable("nearby", response.status_code)
        try:
            items = response.json().get("places", [])  # 該当なしは {} が返る
        except ValueError as exc:
            raise _unavailable("nearby", response.status_code) from exc
        if not isinstance(items, list):
            raise _unavailable("nearby", response.status_code)
        return [place for place in (_parse_place(item) for item in items) if place is not None]

    def place_exists(self, google_place_id: str) -> bool:
        if not _PLACE_ID_PATTERN.fullmatch(google_place_id):
            return False
        response = self._send(
            "GET",
            f"/places/{quote(google_place_id, safe='')}",
            headers={"X-Goog-FieldMask": "id"},
        )
        if response.status_code == 200:
            try:
                return response.json().get("id") == google_place_id
            except ValueError as exc:
                raise _unavailable("details", response.status_code) from exc
        # 存在しないID（NOT_FOUND）・形式が不正なID（INVALID_ARGUMENT）
        if response.status_code in (400, 404):
            return False
        # 401/403（キー・権限）、429（Google側の上限）、5xx は利用不能
        raise _unavailable("details", response.status_code)

    def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # 例外の文字列はURLを含みうるため型名だけを記録する。タイムアウトも503（API仕様）
            logger.warning("google_places_error type=%s", type(exc).__name__)
            raise ApiError(503, "service_unavailable") from exc


def _unavailable(operation: str, status_code: int) -> ApiError:
    logger.warning("google_places_unavailable operation=%s status=%s", operation, status_code)
    return ApiError(503, "service_unavailable")


def _parse_place(item: object) -> GooglePlace | None:
    if not isinstance(item, dict):
        return None
    place_id = item.get("id")
    location = item.get("location") or {}
    latitude, longitude = location.get("latitude"), location.get("longitude")
    if not isinstance(place_id, str) or not _PLACE_ID_PATTERN.fullmatch(place_id):
        return None
    if not _is_coordinate(latitude, 90) or not _is_coordinate(longitude, 180):
        return None
    display_name = item.get("displayName") or {}
    name = display_name.get("text") if isinstance(display_name, dict) else None
    address = item.get("shortFormattedAddress") or item.get("formattedAddress") or ""
    return GooglePlace(
        google_place_id=place_id,
        name=name if isinstance(name, str) else "",
        latitude=float(latitude),
        longitude=float(longitude),
        address=address if isinstance(address, str) else "",
    )


def _is_coordinate(value: object, limit: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and -limit <= value <= limit
    )


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """2点間の大圏距離（m、整数に丸める）。"""
    radius = 6_371_008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return round(2 * radius * math.asin(min(1.0, math.sqrt(a))))


@lru_cache(maxsize=2)
def _create(api_key: str) -> PlacesClient:
    return PlacesClient(api_key)


def get_places_client(settings: Settings = Depends(get_settings)) -> PlacesClient:
    if settings.google_maps_server_api_key is None:
        raise ApiError(503, "service_unavailable")
    key = settings.google_maps_server_api_key.get_secret_value()
    if not key:
        raise ApiError(503, "service_unavailable")
    return _create(key)


def verify_place_exists(client: PlacesClient, google_place_id: str) -> None:
    """03の解析で店舗が指定された場合だけ呼ぶ。存在しなければ404 place_not_found。"""
    if not client.place_exists(google_place_id):
        raise ApiError(404, "place_not_found")


def get_optional_places_client(settings: Settings = Depends(get_settings)) -> PlacesClient | None:
    """店舗の指定が任意のAPI（03の解析）用。キーが未設定なら None とし、店舗が指定されたときだけ503にする。"""
    key = settings.google_maps_server_api_key.get_secret_value() if settings.google_maps_server_api_key else ""
    return _create(key) if key else None
