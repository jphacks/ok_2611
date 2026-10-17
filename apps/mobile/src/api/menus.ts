import { ApiError, getAccountToken } from "./auth";
import { apiEndpoints, isEndpointConfigured } from "./endpoints";

export type MenuAllergenPrediction = {
  allergen_id: number;
  display_name: string;
  prediction: { status: string; basis: string };
};
export type MenuDish = {
  dish_id: string;
  name: string;
  display_name: string;
  description: string | null;
  price: number | null;
  currency: string | null;
  allergens: MenuAllergenPrediction[];
};
export type MenuAnalysis = {
  menu_id: string;
  google_place_id: string | null;
  analysis_token: string;
  analysis_expires_at: string;
  dishes: MenuDish[];
};

export const isMenuAnalysisConfigured = isEndpointConfigured("analyzeMenu");

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
