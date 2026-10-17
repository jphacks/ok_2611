import { ApiError, getAccountToken } from "./auth";
import { apiEndpoints, isEndpointConfigured } from "./endpoints";

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
    answer: "contains" | "shared_utensils" | "does_not_contain" | "unknown";
    confirmed_at: string;
  } | null;
  store_history: {
    match_basis: "name_key";
    last_confirmed_at: string;
    answer_counts: { contains: number; shared_utensils: number; does_not_contain: number; unknown: number };
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

export const isMenuAnalysisConfigured = isEndpointConfigured("analyzeMenu");

export const isMenuResultConfigured = isEndpointConfigured("getMenu");

export async function getMenuResult(menuId: string, analysisToken: string, allergenIds: number[]): Promise<MenuResult> {
  const base = apiEndpoints.getMenu.trim();
  if (!base) throw new ApiError(0, "api_not_configured", "The result API is not connected yet.");
  const url = new URL(`${base.replace(/\/$/, "")}/${encodeURIComponent(menuId)}`);
  url.searchParams.set("allergen_ids", allergenIds.join(","));
  url.searchParams.set("locale", "en");
  let response: Response;
  try {
    response = await fetch(url.toString(), { headers: { Authorization: `Bearer ${analysisToken}` }, cache: "no-store" });
  } catch {
    throw new ApiError(0, "network_error", "Could not refresh the menu result.");
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const apiError = payload && typeof payload === "object" && "error" in payload
      ? (payload as { error?: { code?: string; message?: string } }).error : undefined;
    throw new ApiError(response.status, apiError?.code ?? "request_failed", apiError?.message ?? "Could not refresh the menu result.");
  }
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
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body,
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) throw new ApiError(504, "timeout", "Analysis took too long. Try again.");
    throw new ApiError(0, "network_error", "Could not connect. Try again.");
  } finally {
    clearTimeout(timeout);
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = payload && typeof payload === "object" && "error" in payload
      ? (payload as { error?: { code?: string; message?: string } }).error : undefined;
    throw new ApiError(response.status, error?.code ?? "request_failed", error?.message ?? "Analysis failed. Try again.");
  }
  const result = payload as MenuAnalysis | null;
  if (!result?.menu_id || !result.analysis_token || !Array.isArray(result.dishes)) {
    throw new ApiError(0, "invalid_response", "The analysis response was incomplete.");
  }
  return result;
}
