import { ApiError } from "./auth";
import { apiEndpoints, isEndpointConfigured } from "./endpoints";

export type AllergenSelection = { allergen_ids: number[] };

export const isAllergenSaveConfigured = isEndpointConfigured("saveAllergens");

export async function saveAllergens(allergenIds: number[], accountToken: string): Promise<AllergenSelection> {
  const url = apiEndpoints.saveAllergens.trim();
  if (!url) {
    throw new ApiError(0, "api_not_configured", "The allergen API URL is not configured.");
  }
  if (!accountToken) {
    throw new ApiError(401, "unauthorized", "Log in before saving your profile.");
  }
  if (allergenIds.length === 0) {
    throw new ApiError(422, "invalid_allergen_ids", "Select at least one allergen.");
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: "PUT",
      headers: {
        "Authorization": `Bearer ${accountToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ allergen_ids: allergenIds }),
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not connect. Please try again.");
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(response.status, error?.code ?? "request_failed", error?.message ?? "Could not save your profile.");
  }
  const saved = payload as AllergenSelection | null;
  if (!Array.isArray(saved?.allergen_ids)) {
    throw new ApiError(0, "invalid_response", "The server response was incomplete.");
  }
  return saved;
}
