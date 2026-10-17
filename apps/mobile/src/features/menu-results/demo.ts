import rawMenu from "./okinawa-menu-v4.json";
import { allergenOptions } from "../../content/preferences";
import type { MenuAllergen, MenuDish, MenuResult } from "../../api/menus";

const selectedAllergenIds = [3, 23] as const; // Wheat, Pork
const nameById = new Map(allergenOptions.map((item) => [item.id, item.display_name]));

function candidateFor(
  item: { status: string; source: string; evidence: string } | undefined,
): MenuAllergen["ai"] {
  if (!item) return { status: "unknown", source: "unavailable", evidence: "", weight: null };
  const status = item.status === "explicit_present" ? "explicit_present" :
    item.status === "possible" ? "possible" : "unknown";
  const source = item.source === "menu_text" || item.source === "recipe_inference" ||
    item.source === "dish_name_inference" ? item.source : "unavailable";
  return { status, source, evidence: item.evidence, weight: null };
}

function firstAnalysisAllergen(id: number, source: { allergen_id: number; status: string; source: string; evidence: string } | undefined): MenuAllergen {
  return {
    allergen_id: id,
    display_name: nameById.get(id) || `Allergen ${id}`,
    ai: candidateFor(source),
    current_answer: null,
    store_history: null,
    notices: {
      ai_staff_mismatch: false,
      recheck_current_answer: false,
      history_conflict: false,
      history_shared_utensils: false,
    },
  };
}

export function okinawaMenuDemo(): MenuResult {
  const dishes: MenuDish[] = rawMenu.dishes.map((source, index) => {
    const allIds = [...new Set([...source.allergens.map((item) => item.allergen_id), ...selectedAllergenIds])];
    const allergens = allIds.map((id) => firstAnalysisAllergen(
      id,
      source.allergens.find((item) => item.allergen_id === id),
    ));
    return {
      dish_id: `local-okinawa-${index + 1}`,
      dish_version: 1,
      name: source.name,
      display_name: source.translations.en.name,
      description: source.translations.en.description,
      price: source.price,
      currency: source.currency,
      allergens,
      dietary_restrictions: [],
    };
  });
  return {
    menu_id: "local-preview-okinawa-menu",
    google_place_id: null,
    analysis_expires_at: "2026-10-19T00:00:00Z",
    ai_model: "local-api-fixture",
    prompt_version: "v4",
    analyzed_at: "2026-10-18T00:00:00Z",
    locale: "en",
    dishes,
  };
}
