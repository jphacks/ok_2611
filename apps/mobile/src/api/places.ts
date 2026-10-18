import { ApiError, requestJson } from "./client";
import { apiEndpoints } from "./endpoints";

export type NearbyPlace = {
  google_place_id: string;
  name: string;
  latitude: number;
  longitude: number;
  address: string;
  distance_m: number;
  has_public_menus: boolean;
  public_menu_count: number;
};
export type NearbyPlaces = { places: NearbyPlace[]; attribution: string };

function isPlace(value: unknown): value is NearbyPlace {
  if (!value || typeof value !== "object") return false;
  const place = value as Partial<NearbyPlace>;
  return typeof place.google_place_id === "string" && /^[A-Za-z0-9_-]{1,255}$/.test(place.google_place_id) &&
    typeof place.name === "string" && place.name.trim().length > 0 && typeof place.address === "string" &&
    typeof place.latitude === "number" && Number.isFinite(place.latitude) && Math.abs(place.latitude) <= 90 &&
    typeof place.longitude === "number" && Number.isFinite(place.longitude) && Math.abs(place.longitude) <= 180 &&
    typeof place.distance_m === "number" && Number.isInteger(place.distance_m) && place.distance_m >= 0 &&
    typeof place.has_public_menus === "boolean" && typeof place.public_menu_count === "number" &&
    Number.isInteger(place.public_menu_count) && place.public_menu_count >= 0;
}

// Public FastAPI endpoint: no account token, Google key, or direct database access.
// ⑥ map and ⑧ selection share one radius so any restaurant selectable in ⑧ also appears on the map
// (500 m, user decision 2026-10-18). Must stay within the API range of 50–1000 m.
export const nearbySearchRadiusM = 500;

export async function getNearbyPlaces(latitude: number, longitude: number, signal: AbortSignal, radiusM = nearbySearchRadiusM): Promise<NearbyPlaces> {
  if (!Number.isInteger(radiusM) || radiusM < 50 || radiusM > 1000) throw new RangeError("radiusM must be 50–1000.");
  if (!Number.isFinite(latitude) || Math.abs(latitude) > 90 || !Number.isFinite(longitude) || Math.abs(longitude) > 180) {
    throw new ApiError(422, "invalid_location", "Your location could not be read. Try again or skip.");
  }
  const url = new URL(apiEndpoints.nearbyPlaces);
  url.search = new URLSearchParams({ lat: String(latitude), lng: String(longitude), radius_m: String(radiusM), locale: "en" }).toString();
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal.addEventListener("abort", cancel, { once: true });
  if (signal.aborted) cancel();
  const timer = setTimeout(cancel, 10_000);
  try {
    const { payload } = await requestJson(url.toString(), {
      signal: controller.signal,
      credentials: "omit",
      networkMessage: "Could not connect. Try again or skip.",
      failureMessage: "Could not load nearby restaurants. Try again or skip.",
    });
    const result = payload as Partial<NearbyPlaces> | null;
    if (!result || !Array.isArray(result.places) || result.places.length > 20 ||
      !result.places.every(isPlace) || typeof result.attribution !== "string" || !result.attribution.trim()) {
      throw new ApiError(0, "invalid_response", "The restaurant list was incomplete. Try again or skip.");
    }
    return { places: result.places, attribution: result.attribution };
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", cancel);
  }
}
