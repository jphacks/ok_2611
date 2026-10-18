// Loads the Google Maps JavaScript API once per page with the public browser key. The key is restricted by
// HTTP referrer in Google Cloud; it is not a secret, but the script URL is never logged or shown.
export type LatLng = { lat: number; lng: number };
export type GoogleMap = { panTo(position: LatLng): void; setCenter(position: LatLng): void };
export type GoogleMarker = HTMLElement & { map: GoogleMap | null; position: LatLng | null; title: string; content: Node | null };
export type GoogleMapsLibraries = {
  Map: new (element: HTMLElement, options: Record<string, unknown>) => GoogleMap;
  AdvancedMarkerElement: new (options: Record<string, unknown>) => GoogleMarker;
};
export type MapLoadFailure = "not_configured" | "timeout" | "load_failed" | "auth_failed";

export class MapLoadError extends Error {
  constructor(public readonly reason: MapLoadFailure) {
    super(reason);
  }
}

type GoogleGlobal = { maps?: { importLibrary?: (name: string) => Promise<Record<string, unknown>> } };
type MapsWindow = Window & { google?: GoogleGlobal; gm_authFailure?: () => void; __meelyzeMapsReady?: () => void };

const browserKey = process.env.EXPO_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY?.trim() ?? "";
// Advanced markers need a Map ID. DEMO_MAP_ID is Google's testing ID; set your own before production.
export const mapId = process.env.EXPO_PUBLIC_GOOGLE_MAPS_MAP_ID?.trim() || "DEMO_MAP_ID";
export const isMapConfigured = browserKey.length > 0;

const loadTimeoutMs = 15_000;
let loading: Promise<GoogleMapsLibraries> | null = null;
let authFailed = false;
const authListeners = new Set<() => void>();

// Google calls gm_authFailure when the key, referrer, or billing check fails, sometimes after the script loaded.
export function onMapAuthFailure(listener: () => void): () => void {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

async function importLibraries(google: GoogleGlobal): Promise<GoogleMapsLibraries> {
  const importLibrary = google.maps?.importLibrary;
  if (!importLibrary) throw new MapLoadError("load_failed");
  const [maps, marker] = await Promise.all([importLibrary("maps"), importLibrary("marker")]);
  if (typeof maps.Map !== "function" || typeof marker.AdvancedMarkerElement !== "function") throw new MapLoadError("load_failed");
  return { Map: maps.Map, AdvancedMarkerElement: marker.AdvancedMarkerElement } as GoogleMapsLibraries;
}

// Shared by every map on the page. A failure clears the cached promise so a later retry can load again.
export function loadGoogleMaps(): Promise<GoogleMapsLibraries> {
  if (typeof window === "undefined" || typeof document === "undefined") return Promise.reject(new MapLoadError("load_failed"));
  if (!isMapConfigured) return Promise.reject(new MapLoadError("not_configured"));
  if (authFailed) return Promise.reject(new MapLoadError("auth_failed"));
  if (loading) return loading;
  const target = window as MapsWindow;
  target.gm_authFailure = () => {
    authFailed = true;
    loading = null;
    authListeners.forEach((listener) => listener());
  };
  const attempt = new Promise<GoogleMapsLibraries>((resolve, reject) => {
    let script: HTMLScriptElement | null = null;
    let settled = false;
    const finish = (error: MapLoadError | null, libraries?: GoogleMapsLibraries) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      delete target.__meelyzeMapsReady;
      if (error) {
        // Remove a half-loaded script so a retry starts clean instead of including the API twice.
        if (!target.google?.maps?.importLibrary) script?.remove();
        reject(error);
      } else resolve(libraries!);
    };
    const timer = setTimeout(() => finish(new MapLoadError("timeout")), loadTimeoutMs);
    const ready = () => {
      importLibraries(target.google ?? {}).then(
        (libraries) => finish(authFailed ? new MapLoadError("auth_failed") : null, libraries),
        () => finish(new MapLoadError("load_failed")),
      );
    };
    if (target.google?.maps?.importLibrary) { ready(); return; }
    target.__meelyzeMapsReady = ready;
    script = document.createElement("script");
    script.async = true;
    script.src = `https://maps.googleapis.com/maps/api/js?${new URLSearchParams({
      key: browserKey, v: "weekly", loading: "async", callback: "__meelyzeMapsReady", language: "en",
    }).toString()}`;
    script.onerror = () => finish(new MapLoadError("load_failed"));
    document.head.appendChild(script);
  });
  loading = attempt;
  attempt.catch(() => { if (loading === attempt) loading = null; });
  return attempt;
}

export function mapLoadMessage(reason: MapLoadFailure): string {
  switch (reason) {
    case "not_configured": return "The map is not set up in this build. You can still pick a restaurant from the list below.";
    case "auth_failed": return "The map could not be authorised. You can still pick a restaurant from the list below.";
    case "timeout": return "The map took too long to load. Try again, or pick a restaurant from the list below.";
    default: return "The map could not be loaded. Try again, or pick a restaurant from the list below.";
  }
}
