"""アレルゲン・食事制限マスタの取得。MVPの表示名は英語（locale=en）だけ。"""

from supabase import Client

from app.schemas.common import Locale
from app.schemas.masters import AllergenItem, DietaryRestrictionItem


def list_allergens(client: Client, locale: Locale) -> list[AllergenItem]:
    rows = (
        client.table("allergens")
        .select("id,code,name,name_en,category,display_order")
        .order("display_order")
        .execute()
        .data
    )
    return [AllergenItem(**row, display_name=row["name_en"]) for row in rows]


def list_dietary_restrictions(client: Client, locale: Locale) -> list[DietaryRestrictionItem]:
    rows = (
        client.table("dietary_restrictions")
        .select("id,code,name,name_en")
        .order("id")
        .execute()
        .data
    )
    return [
        DietaryRestrictionItem(id=row["id"], code=row["code"], name=row["name"], display_name=row["name_en"])
        for row in rows
    ]
