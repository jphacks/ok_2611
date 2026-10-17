"""API 2・13 のマスタ。形式は contracts/openapi.yaml の allergen_master_item・dietary_master_item。"""

from typing import Annotated, Literal

from pydantic import Field

from app.schemas.common import StrictModel


class AllergenItem(StrictModel):
    id: Annotated[int, Field(ge=1, le=29)]
    code: str
    name: str
    name_en: str
    display_name: str
    category: Literal["required", "recommended"]
    display_order: Annotated[int, Field(ge=1, le=29)]


class AllergensResponse(StrictModel):
    allergens: Annotated[list[AllergenItem], Field(min_length=29, max_length=29)]


class DietaryRestrictionItem(StrictModel):
    id: Annotated[int, Field(ge=1, le=4)]
    code: Literal["vegan", "vegetarian", "halal", "no_alcohol"]
    name: str
    display_name: str


class DietaryRestrictionsResponse(StrictModel):
    dietary_restrictions: Annotated[list[DietaryRestrictionItem], Field(min_length=4, max_length=4)]
