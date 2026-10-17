import { ApiError, requestJson } from "./client";
import { getAccountToken } from "./auth";
import { apiEndpoints, isEndpointConfigured } from "./endpoints";

export type StaffAnswer = "contains" | "shared_utensils" | "does_not_contain" | "unknown";
type AnswerCounts = Record<StaffAnswer, number>;

export type MenuAllergen = {
  allergen_id: number;
  display_name: string;
  ai: {
    status: "explicit_present" | "possible" | "unknown";
    source: "menu_text" | "recipe_inference" | "dish_name_inference" | "unavailable";
    evidence: string;
    weight: number | null;
  };
  current_answer: {
    answer: StaffAnswer;
    confirmed_at: string;
  } | null;
  store_history: {
    match_basis: "name_key";
    answer_counts: AnswerCounts;
    last_answered_at: Record<StaffAnswer, string | null>;
    last_confirmed_at: string;
    alpha: number;
    beta: number;
    score: number | null;
    has_conflict: boolean;
  } | null;
  notices: {
    ai_staff_mismatch: boolean;
    recheck_current_answer: boolean;
    history_conflict: boolean;
    history_shared_utensils: boolean;
  };
};
export type MenuDish = {
  dish_id: string;
  dish_version: number;
  name: string;
  display_name: string;
  description: string;
  price: number | null;
  currency: string;
  allergens: MenuAllergen[];
  dietary_restrictions: unknown[];
};
export type MenuResult = {
  menu_id: string;
  google_place_id: string | null;
  analysis_expires_at: string;
  ai_model: string;
  prompt_version: "v4" | "v5";
  analyzed_at: string;
  locale: "en";
  dishes: MenuDish[];
};
export type MenuAnalysis = MenuResult & { analysis_token: string };

export type ConfirmationAnswer = { dish_id: string; allergen_id: number; answer: StaffAnswer };
export type ConfirmationRequest = {
  request_id: string;
  answers: ConfirmationAnswer[];
  dietary_answers: [];
  publish_consent: boolean;
  locale: "en";
};
export type ConfirmedAllergen = Omit<MenuAllergen, "current_answer"> & { answer: StaffAnswer; answer_label: string };
export type ConfirmedDish = {
  dish_id: string;
  display_name: string;
  allergens: ConfirmedAllergen[];
  dietary_restrictions: unknown[];
};
export type ConfirmationResult = {
  session_id: string;
  confirmed_at: string;
  publish_consent: boolean;
  user_publish_consent: boolean;
  is_public: boolean;
  replayed: boolean;
  results: ConfirmedDish[];
};

export const isMenuAnalysisConfigured = isEndpointConfigured("analyzeMenu");

export const isMenuResultConfigured = isEndpointConfigured("getMenu");

function menuUrl(base: string, menuId: string, suffix = ""): URL {
  return new URL(`${base.replace(/\/$/, "")}/${encodeURIComponent(menuId)}${suffix}`);
}

export async function getMenuResult(menuId: string, analysisToken: string, allergenIds: number[]): Promise<MenuResult> {
  const base = apiEndpoints.getMenu.trim();
  if (!base) throw new ApiError(0, "api_not_configured", "The result API is not connected yet.");
  const url = menuUrl(base, menuId);
  url.searchParams.set("allergen_ids", allergenIds.join(","));
  url.searchParams.set("locale", "en");
  const { payload } = await requestJson(url.toString(), {
    headers: { Authorization: `Bearer ${analysisToken}` },
    networkMessage: "Could not refresh the menu result.",
    failureMessage: "Could not refresh the menu result.",
  });
  const result = payload as MenuResult | null;
  if (!result || result.menu_id !== menuId || !Array.isArray(result.dishes)) {
    throw new ApiError(0, "invalid_response", "The refreshed menu result was incomplete.");
  }
  return result;
}

export async function analyzeMenu(image: File, allergenIds: number[], placeId?: string): Promise<MenuAnalysis> {
  const url = apiEndpoints.analyzeMenu.trim();
  if (!url) throw new ApiError(0, "api_not_configured", "The analysis API is not connected yet.");
  if (allergenIds.length === 0) throw new ApiError(422, "invalid_allergen_ids", "Select at least one allergen first.");
  const token = getAccountToken();
  if (!token) throw new ApiError(401, "login_required", "Log in before analyzing a menu.");
  const body = new FormData();
  body.append("image", image, image.name);
  for (const id of allergenIds) body.append("allergen_ids", String(id));
  if (placeId) body.append("google_place_id", placeId);
  body.append("locale", "en");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45_000);
  let payload: unknown;
  try {
    ({ payload } = await requestJson(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body,
      signal: controller.signal,
      networkMessage: "Could not connect. Try again.",
      failureMessage: "Analysis failed. Try again.",
    }));
  } finally {
    clearTimeout(timeout);
  }
  const result = payload as MenuAnalysis | null;
  if (!result?.menu_id || !result.analysis_token || !Array.isArray(result.dishes)) {
    throw new ApiError(0, "invalid_response", "The analysis response was incomplete.");
  }
  return result;
}

// Saves the staff answers and the staff's publish choice in one request (API 6).
// A resend with the same request_id and body is answered with replayed=true instead of a second record.
export async function createConfirmation(menuId: string, analysisToken: string, body: ConfirmationRequest): Promise<ConfirmationResult> {
  const base = apiEndpoints.createConfirmation.trim();
  if (!base) throw new ApiError(0, "api_not_configured", "The confirmation API is not connected yet.");
  const { payload } = await requestJson(menuUrl(base, menuId, "/confirmations").toString(), {
    method: "POST",
    headers: { Authorization: `Bearer ${analysisToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    networkMessage: "Could not connect. Please try again.",
    failureMessage: "Could not save the staff answers.",
  });
  const result = payload as ConfirmationResult | null;
  if (!result?.session_id || typeof result.is_public !== "boolean" || !Array.isArray(result.results)) {
    throw new ApiError(0, "invalid_response", "The confirmation response was incomplete.");
  }
  return result;
}
