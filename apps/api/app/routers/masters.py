from typing import Annotated

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.schemas.common import VALIDATION_ERROR_RESPONSES, LocaleQuery
from app.schemas.masters import AllergensResponse, DietaryRestrictionsResponse
from app.services import masters
from app.services.supabase_client import get_supabase_client

router = APIRouter(tags=["P0"], responses=VALIDATION_ERROR_RESPONSES)


@router.get("/allergens", operation_id="get_allergens", response_model=AllergensResponse)
def get_allergens(
    query: Annotated[LocaleQuery, Query()],
    client: Annotated[Client, Depends(get_supabase_client)],
) -> AllergensResponse:
    return AllergensResponse(allergens=masters.list_allergens(client, query.locale))


@router.get(
    "/dietary-restrictions",
    operation_id="get_dietary_restrictions",
    response_model=DietaryRestrictionsResponse,
)
def get_dietary_restrictions(
    query: Annotated[LocaleQuery, Query()],
    client: Annotated[Client, Depends(get_supabase_client)],
) -> DietaryRestrictionsResponse:
    return DietaryRestrictionsResponse(
        dietary_restrictions=masters.list_dietary_restrictions(client, query.locale)
    )
