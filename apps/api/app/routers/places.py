from typing import Annotated

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.dependencies import client_ip, no_store
from app.schemas.common import ErrorResponse, VALIDATION_ERROR_RESPONSES
from app.schemas.places import NearbyPlace, NearbyPlacesResponse, NearbyQuery
from app.services.places import (
    ATTRIBUTION,
    MAX_RESULTS,
    PlacesClient,
    distance_m,
    get_places_client,
)
from app.services.publication import count_public_dishes
from app.services.rate_limit import RateLimiter, RateLimitRule, enforce_rate_limit, get_rate_limiter
from app.services.supabase_client import get_supabase_client

router = APIRouter(tags=["P0"], responses=VALIDATION_ERROR_RESPONSES)

NEARBY_RATE_LIMIT = RateLimitRule(name="places_nearby_ip", limit=30, window_seconds=60)


@router.get(
    "/places/nearby",
    operation_id="get_nearby_places",
    response_model=NearbyPlacesResponse,
    # 座標から導いた結果を中間のキャッシュに残さない
    dependencies=[Depends(no_store)],
    responses={
        429: {"model": ErrorResponse, "description": "rate_limited"},
        503: {"model": ErrorResponse, "description": "service_unavailable（Googleが利用できない）"},
    },
)
def get_nearby_places(
    query: Annotated[NearbyQuery, Query()],
    ip: Annotated[str, Depends(client_ip)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    places_client: Annotated[PlacesClient, Depends(get_places_client)],
    db: Annotated[Client, Depends(get_supabase_client)],
) -> NearbyPlacesResponse:
    enforce_rate_limit(limiter, NEARBY_RATE_LIMIT, ip)

    places = places_client.search_nearby(query.lat, query.lng, query.radius_m, query.locale)
    measured = sorted(
        ((distance_m(query.lat, query.lng, p.latitude, p.longitude), p) for p in places),
        key=lambda pair: (pair[0], pair[1].google_place_id),
    )
    # Googleが同じ店舗を重複して返した場合は近い方だけを残す
    seen: set[str] = set()
    unique = []
    for distance, place in measured:
        if place.google_place_id not in seen:
            seen.add(place.google_place_id)
            unique.append((distance, place))
    unique = unique[:MAX_RESULTS]

    # ⑦で表示される料理数（同じ店舗の name_key の種類数）
    counts = count_public_dishes(db, [place.google_place_id for _, place in unique])
    return NearbyPlacesResponse(
        places=[
            NearbyPlace(
                google_place_id=place.google_place_id,
                name=place.name,
                latitude=place.latitude,
                longitude=place.longitude,
                address=place.address,
                distance_m=distance,
                has_public_menus=counts.get(place.google_place_id, 0) > 0,
                public_menu_count=counts.get(place.google_place_id, 0),
            )
            for distance, place in unique
        ],
        attribution=ATTRIBUTION,
    )
