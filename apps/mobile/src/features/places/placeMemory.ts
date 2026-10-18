// The restaurant picked on ⑥ or ⑧, kept in memory only. Routes carry just the Place ID, so Google's name and
// attribution never reach the URL, storage, or the API. A reload loses it and the screens fall back to "Selected restaurant".
export type RememberedPlace = { google_place_id: string; name: string; attribution: string };

const placeIdPattern = /^[A-Za-z0-9_-]{1,255}$/;
let remembered: RememberedPlace | null = null;

export function isPlaceId(value: unknown): value is string {
  return typeof value === "string" && placeIdPattern.test(value);
}

export function rememberPlace(place: RememberedPlace): void {
  // Copies only these fields so coordinates or other Google data are not kept.
  remembered = isPlaceId(place.google_place_id)
    ? { google_place_id: place.google_place_id, name: place.name, attribution: place.attribution }
    : null;
}

// Only returns the remembered details for the same Place ID, so another restaurant's name is never shown.
export function getRememberedPlace(placeId: string | undefined | null): RememberedPlace | null {
  return placeId && remembered?.google_place_id === placeId ? remembered : null;
}

export function rememberedPlaceName(placeId: string | undefined | null): string {
  return getRememberedPlace(placeId)?.name || "Selected restaurant";
}

export function forgetPlace(): void {
  remembered = null;
}
