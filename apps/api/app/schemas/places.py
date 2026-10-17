"""API 3 `GET /places/nearby`。形式は contracts/openapi.yaml の nearby_places_response。"""

from typing import Annotated

from pydantic import Field

from app.schemas.common import Locale, StrictModel


class NearbyQuery(StrictModel):
    lat: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
    lng: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
    radius_m: Annotated[int, Field(ge=50, le=1000)] = 300
    locale: Locale = "en"


class NearbyPlace(StrictModel):
    google_place_id: Annotated[str, Field(min_length=1, max_length=255)]
    name: str
    latitude: Annotated[float, Field(ge=-90, le=90)]
    longitude: Annotated[float, Field(ge=-180, le=180)]
    address: str
    distance_m: Annotated[int, Field(ge=0)]
    has_public_menus: bool
    public_menu_count: Annotated[int, Field(ge=0)]


class NearbyPlacesResponse(StrictModel):
    places: Annotated[list[NearbyPlace], Field(max_length=20)]
    attribution: str
