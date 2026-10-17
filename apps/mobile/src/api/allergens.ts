import { ApiError, requestJson } from "./client";
import { apiEndpoints, isEndpointConfigured } from "./endpoints";

export type AllergenSelection = { allergen_ids: number[] };

export const isAllergenSaveConfigured = isEndpointConfigured("saveAllergens");

function readSelection(payload: unknown): AllergenSelection {
  const saved = payload as AllergenSelection | null;
  if (!Array.isArray(saved?.allergen_ids) || saved.allergen_ids.some((id) => !Number.isInteger(id))) {
    throw new ApiError(0, "invalid_response", "The server response was incomplete.");
  }
  return saved;
}

export async function getMyAllergens(accountToken: string): Promise<AllergenSelection> {
  const { payload } = await requestJson(apiEndpoints.myAllergens, {
    headers: { Authorization: `Bearer ${accountToken}` },
    networkMessage: "Could not load your allergens. Please try again.",
    failureMessage: "Could not load your allergens.",
  });
  return readSelection(payload);
}

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
  const { payload } = await requestJson(url, {
    method: "PUT",
    headers: {
      "Authorization": `Bearer ${accountToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ allergen_ids: allergenIds }),
    networkMessage: "Could not connect. Please try again.",
    failureMessage: "Could not save your profile.",
  });
  return readSelection(payload);
}
