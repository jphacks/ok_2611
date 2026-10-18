import { ApiError, requestJson } from "./client";
import { apiEndpoints } from "./endpoints";
import { isPlaceId } from "../features/places/placeMemory";

// API 7 `GET /places/{google_place_id}/public-menus`. Public aggregate only: no menu, dish, or session IDs,
// no current answer, images, or account data. Answers were entered on travellers' phones and are unverified.
export type AllergenAiStatus = "explicit_present" | "possible" | "unknown";
export type DietaryAiStatus = "explicit_conflict" | "possible_conflict" | "unknown";
export type AiSource = "menu_text" | "recipe_inference" | "dish_name_inference" | "unavailable";
export type AllergenAnswerKey = "contains" | "shared_utensils" | "does_not_contain" | "unknown";
export type DietaryAnswerKey = "not_supported" | "cross_contact" | "supported" | "unknown";

type StoreHistory<K extends string> = {
  match_basis: "name_key";
  last_confirmed_at: string;
  alpha: number;
  beta: number;
  score: number | null;
  has_conflict: boolean;
  answer_counts: Record<K, number>;
  last_answered_at: Record<K, string | null>;
};

export type PublicAllergen = {
  allergen_id: number;
  display_name: string;
  ai: { status: AllergenAiStatus; source: AiSource; evidence: string; weight: number | null };
  store_history: StoreHistory<AllergenAnswerKey> | null;
  notices: { history_conflict: boolean; history_shared_utensils: boolean };
};

export type PublicDietary = {
  dietary_restriction_id: number;
  display_name: string;
  ai: { status: DietaryAiStatus; source: AiSource; evidence: string; weight: number | null };
  store_history: StoreHistory<DietaryAnswerKey> | null;
  notices: { history_conflict: boolean; history_cross_contact: boolean };
};

export type PublicDish = {
  name_key: string;
  name: string;
  display_name: string;
  description: string;
  price: number | null;
  currency: string;
  allergens: PublicAllergen[];
  dietary_restrictions: PublicDietary[];
};

export type PublicMenus = {
  google_place_id: string;
  match_basis: "name_key";
  staff_answers_verified: false;
  dishes: PublicDish[];
};

export const allergenAnswerKeys: readonly AllergenAnswerKey[] = ["contains", "shared_utensils", "does_not_contain", "unknown"];
const dietaryAnswerKeys: readonly DietaryAnswerKey[] = ["not_supported", "cross_contact", "supported", "unknown"];
const sources = new Set<string>(["menu_text", "recipe_inference", "dish_name_inference", "unavailable"]);

const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const isCount = (value: unknown) => typeof value === "number" && Number.isInteger(value) && value >= 0;
const isNumber = (value: unknown) => typeof value === "number" && Number.isFinite(value);
const isDate = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value));
const isNullableNumber = (value: unknown) => value === null || isNumber(value);

function isAi(value: unknown, statuses: readonly string[]): boolean {
  return isObject(value) && statuses.includes(value.status as string) && sources.has(value.source as string) &&
    typeof value.evidence === "string" && isNullableNumber(value.weight);
}

function isHistory(value: unknown, keys: readonly string[]): boolean {
  if (value === null) return true;
  if (!isObject(value) || value.match_basis !== "name_key" || !isDate(value.last_confirmed_at) ||
    !isNumber(value.alpha) || !isNumber(value.beta) || !isNullableNumber(value.score) ||
    typeof value.has_conflict !== "boolean") return false;
  const counts = value.answer_counts;
  const dates = value.last_answered_at;
  return isObject(counts) && isObject(dates) &&
    keys.every((key) => isCount(counts[key]) && (dates[key] === null || isDate(dates[key])));
}

function isAllergen(value: unknown): boolean {
  return isObject(value) && Number.isInteger(value.allergen_id) && (value.allergen_id as number) >= 1 &&
    (value.allergen_id as number) <= 29 && typeof value.display_name === "string" &&
    isAi(value.ai, ["explicit_present", "possible", "unknown"]) && isHistory(value.store_history, allergenAnswerKeys) &&
    isObject(value.notices) && typeof value.notices.history_conflict === "boolean" &&
    typeof value.notices.history_shared_utensils === "boolean";
}

function isDietary(value: unknown): boolean {
  return isObject(value) && Number.isInteger(value.dietary_restriction_id) && (value.dietary_restriction_id as number) >= 1 &&
    (value.dietary_restriction_id as number) <= 4 && typeof value.display_name === "string" &&
    isAi(value.ai, ["explicit_conflict", "possible_conflict", "unknown"]) && isHistory(value.store_history, dietaryAnswerKeys) &&
    isObject(value.notices) && typeof value.notices.history_conflict === "boolean" &&
    typeof value.notices.history_cross_contact === "boolean";
}

function isDish(value: unknown): boolean {
  return isObject(value) && typeof value.name_key === "string" && value.name_key.length > 0 &&
    typeof value.name === "string" && typeof value.display_name === "string" && typeof value.description === "string" &&
    isNullableNumber(value.price) && typeof value.currency === "string" &&
    Array.isArray(value.allergens) && value.allergens.length <= 29 && value.allergens.every(isAllergen) &&
    Array.isArray(value.dietary_restrictions) && value.dietary_restrictions.length <= 4 && value.dietary_restrictions.every(isDietary);
}

// The request key. Allergen IDs are de-duplicated and sorted so the same selection maps to one request.
export function publicMenusKey(placeId: string, allergenIds: number[]): string {
  return `${placeId}|${normaliseIds(allergenIds).join(",")}|en`;
}

function normaliseIds(ids: number[]): number[] {
  return [...new Set(ids.filter((id) => Number.isInteger(id) && id >= 1 && id <= 29))].sort((a, b) => a - b);
}

// Public FastAPI endpoint: no account or analysis token. Dietary restrictions are not sent because the
// current mobile UI has no setting for them. A caller abort (switching restaurant, closing) is the caller's to ignore.
export async function getPublicMenus(placeId: string, allergenIds: number[], signal: AbortSignal): Promise<PublicMenus> {
  const ids = normaliseIds(allergenIds);
  if (!isPlaceId(placeId)) throw new ApiError(422, "invalid_place", "This restaurant could not be read. Choose it again.");
  if (ids.length === 0) throw new ApiError(422, "allergens_required", "Select your allergens in Profile first.");
  const url = new URL(`${apiEndpoints.publicMenus}/${encodeURIComponent(placeId)}/public-menus`);
  url.search = new URLSearchParams({ allergen_ids: ids.join(","), locale: "en" }).toString();
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
  const timer = setTimeout(cancel, 10_000);
  try {
    const { payload } = await requestJson(url.toString(), {
      signal: controller.signal,
      credentials: "omit",
      networkMessage: "Could not connect. Try again.",
      failureMessage: "Could not load shared menus. Try again.",
    });
    if (!isObject(payload) || payload.google_place_id !== placeId || payload.match_basis !== "name_key" ||
      payload.staff_answers_verified !== false || !Array.isArray(payload.dishes) || !payload.dishes.every(isDish)) {
      throw new ApiError(0, "invalid_response", "The shared menu was incomplete. Try again.");
    }
    return payload as unknown as PublicMenus;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", cancel);
  }
}
