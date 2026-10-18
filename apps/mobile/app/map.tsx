import { useCallback, useRef, useState } from "react";
import { router, useFocusEffect } from "expo-router";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { hasActiveAccountSession } from "../src/api/auth";
import { ApiError } from "../src/api/client";
import { getNearbyPlaces, nearbySearchRadiusM, type NearbyPlace, type NearbyPlaces } from "../src/api/places";
import { getPublicMenus, publicMenusKey } from "../src/api/publicMenus";
import type { LatLng } from "../src/features/map/googleMaps";
import { NearbyMap, pinLabel } from "../src/features/map/NearbyMap";
import { PublicMenuSheet, type PublicMenuState } from "../src/features/map/PublicMenuSheet";
import { getCurrentCoordinates, LocationError } from "../src/features/places/location";
import { rememberPlace } from "../src/features/places/placeMemory";
import { getSelectedAllergenIds } from "../src/features/profile/selection";
import { colors } from "../src/theme";

const cooldownMs = 30_000;
// Per tab, in memory: after a denial the browser is not asked again automatically, even when the Map tab
// mounts a new screen. Cleared by the next successful fix after the user retries.
let locationDenied = false;

function locationMessage(cause: unknown): string {
  const reason = cause instanceof LocationError ? cause.reason : "unavailable";
  switch (reason) {
    case "denied": return "Current location is unavailable: location access is denied. Allow it in your browser settings and try again. You can still scan a menu.";
    case "timeout": return "Current location is unavailable: it took too long. Try again, or scan a menu without it.";
    case "unsupported": return "Current location is unavailable in this browser. Open the app over HTTPS, or scan a menu without it.";
    default: return "Current location is unavailable. Try again, or scan a menu without it.";
  }
}

function searchMessage(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 429) return "Too many searches. Wait a minute before searching again.";
    if (cause.status === 503) return "Restaurant search is unavailable right now. Try again later, or scan a menu.";
    if (cause.code === "timeout") return "Restaurant search took too long. Try again.";
    if (cause.code === "invalid_response") return "The restaurant list was incomplete. Try again.";
  }
  return "Could not load nearby restaurants. Try again, or scan a menu.";
}

function menuMessage(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 429) return "Too many requests. Wait a minute before trying again.";
    if (cause.status === 422) return "Your allergen settings could not be used. Check them in Profile, then try again.";
    if (cause.status === 503) return "Shared menus are unavailable right now. Try again later.";
    if (cause.code === "timeout") return "Loading shared menus took too long. Try again.";
    if (cause.code === "invalid_response") return cause.message;
  }
  return "Could not load shared menus. Try again.";
}

export default function MapScreen() {
  const [center, setCenter] = useState<LatLng | null>(null);
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState("");
  const [nearby, setNearby] = useState<NearbyPlaces | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchCooling, setSearchCooling] = useState(false);
  const [selected, setSelected] = useState<NearbyPlace | null>(null);
  const [menuState, setMenuState] = useState<PublicMenuState>({ status: "loading" });
  const [menuCooling, setMenuCooling] = useState(false);
  const [active, setActive] = useState(false);

  const locateRequest = useRef<AbortController | null>(null);
  const searchRequest = useRef<AbortController | null>(null);
  const menuRequest = useRef<AbortController | null>(null);
  const selectedRef = useRef<NearbyPlace | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());

  const coolDown = useCallback((set: (value: boolean) => void) => {
    set(true);
    const timer = setTimeout(() => { timers.current.delete(timer); set(false); }, cooldownMs);
    timers.current.add(timer);
  }, []);

  const closeSheet = useCallback((restoreFocus = true) => {
    menuRequest.current?.abort();
    menuRequest.current = null;
    selectedRef.current = null;
    setSelected(null);
    const target = returnFocus.current;
    returnFocus.current = null;
    if (restoreFocus && target) setTimeout(() => { if (target.isConnected) target.focus(); }, 0);
  }, []);

  const loadMenus = useCallback(async (place: NearbyPlace) => {
    menuRequest.current?.abort();
    const ids = getSelectedAllergenIds();
    if (ids.length === 0) { menuRequest.current = null; setMenuState({ status: "needs_allergens" }); return; }
    const controller = new AbortController();
    const key = publicMenusKey(place.google_place_id, ids);
    menuRequest.current = controller;
    setMenuState({ status: "loading" });
    try {
      const data = await getPublicMenus(place.google_place_id, ids, controller.signal);
      // Only the latest request for the open restaurant and the same allergen selection is shown.
      if (controller.signal.aborted || menuRequest.current !== controller ||
        publicMenusKey(selectedRef.current?.google_place_id ?? "", getSelectedAllergenIds()) !== key) return;
      setMenuState({ status: "ready", data });
    } catch (cause) {
      if (controller.signal.aborted || menuRequest.current !== controller) return;
      if (cause instanceof ApiError && cause.status === 429) coolDown(setMenuCooling);
      setMenuState({ status: "error", message: menuMessage(cause) });
    }
  }, [coolDown]);

  const openPlace = useCallback((place: NearbyPlace) => {
    if (typeof document !== "undefined" && document.activeElement instanceof HTMLElement) returnFocus.current = document.activeElement;
    selectedRef.current = place;
    setSelected(place);
    void loadMenus(place);
  }, [loadMenus]);

  const search = useCallback(async (origin: LatLng) => {
    searchRequest.current?.abort();
    const controller = new AbortController();
    searchRequest.current = controller;
    setSearching(true);
    setSearchError("");
    try {
      const result = await getNearbyPlaces(origin.lat, origin.lng, controller.signal);
      if (controller.signal.aborted) return;
      setNearby(result);
      // A re-search that drops the open restaurant closes its sheet and discards its request.
      const open = selectedRef.current;
      if (open && !result.places.some((place) => place.google_place_id === open.google_place_id)) closeSheet(false);
      else if (open) {
        const updated = result.places.find((place) => place.google_place_id === open.google_place_id)!;
        selectedRef.current = updated;
        setSelected(updated);
      }
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 429) coolDown(setSearchCooling);
      setSearchError(searchMessage(cause));
    } finally {
      if (searchRequest.current === controller) { searchRequest.current = null; setSearching(false); }
    }
  }, [closeSheet, coolDown]);

  // Gets a fresh location fix, moves the search centre there, and searches once.
  const locate = useCallback(async () => {
    locateRequest.current?.abort();
    const controller = new AbortController();
    locateRequest.current = controller;
    setLocating(true);
    setLocationError("");
    try {
      const coordinates = await getCurrentCoordinates(controller.signal);
      if (controller.signal.aborted) return;
      locationDenied = false;
      const origin = { lat: coordinates.latitude, lng: coordinates.longitude };
      setCenter(origin);
      void search(origin);
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof LocationError && cause.reason === "denied") locationDenied = true;
      setLocationError(locationMessage(cause));
    } finally {
      if (locateRequest.current === controller) { locateRequest.current = null; setLocating(false); }
    }
  }, [search]);

  useFocusEffect(useCallback(() => {
    // Nothing starts behind the layout's login cover: no location prompt, map SDK, or search.
    if (!hasActiveAccountSession()) return;
    setActive(true);
    // After a denial the browser is not asked again automatically; the user retries with the button.
    if (locationDenied) setLocationError(locationMessage(new LocationError("denied", "")));
    else void locate();
    return () => {
      locateRequest.current?.abort();
      searchRequest.current?.abort();
      locateRequest.current = null;
      searchRequest.current = null;
      closeSheet(false);
      for (const timer of timers.current) clearTimeout(timer);
      timers.current.clear();
      // Leaving the screen discards the location, candidates, and shared results held in memory.
      setCenter(null);
      setNearby(null);
      setLocating(false);
      setSearching(false);
      setSearchError("");
      setSearchCooling(false);
      setMenuCooling(false);
    };
  }, [closeSheet, locate]));

  function scanSelected() {
    const place = selectedRef.current;
    if (!place || !nearby) return;
    // A candidate only: ⑧ asks the user to Confirm before the Place ID is used for a scan.
    rememberPlace({ google_place_id: place.google_place_id, name: place.name, attribution: nearby.attribution });
    closeSheet(false);
    router.push({ pathname: "/places/select", params: { google_place_id: place.google_place_id } });
  }

  const busy = locating || searching;
  const places = nearby?.places ?? [];
  const status = locationError || searchError ||
    (nearby && places.length === 0 ? `No restaurants found within ${nearbySearchRadiusM} m. Reload later, or use Scan.` : "");
  // Shown only inside the map area when the map itself cannot be displayed (no key, SDK failure),
  // so shared menus stay reachable. With a working map the pins are the only list.
  const fallbackList = places.length > 0 ? (
    <View style={styles.list}>
      {places.map((place) => (
        <Pressable key={place.google_place_id} accessibilityRole="button" accessibilityLabel={`${pinLabel(place)}, ${place.distance_m} metres away`}
          onPress={() => openPlace(place)} style={styles.place}>
          <View style={styles.placeRow}>
            <Text style={styles.placeName}>{place.name}</Text>
            <Text style={styles.distance}>{place.distance_m} m</Text>
          </View>
          <Text style={[styles.badge, place.has_public_menus ? styles.badgePublic : styles.badgeGeneral]}>
            {place.has_public_menus ? `● ${place.public_menu_count === 1 ? "1 shared dish" : `${place.public_menu_count} shared dishes`}` : "○ No shared menus yet"}
          </Text>
        </Pressable>
      ))}
      <Text style={styles.attribution}>{nearby?.attribution}</Text>
    </View>
  ) : null;
  return (
    <>
      <View style={styles.screen}>
        <View style={styles.header}>
          <View style={styles.titleRow}>
            <Text accessibilityRole="header" style={styles.title}>Map</Text>
            {/* Gets a fresh location and searches once. Panning or zooming the map never searches. */}
            <Pressable accessibilityRole="button" accessibilityLabel={busy ? (locating ? "Finding your location" : "Finding nearby restaurants") : "Reload nearby restaurants"}
              accessibilityState={{ disabled: busy || searchCooling, busy }} disabled={busy || searchCooling}
              onPress={() => { void locate(); }} style={[styles.reload, (busy || searchCooling) && styles.reloadDisabled]}>
              {busy ? <ActivityIndicator color={colors.green} /> : (
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke={colors.green} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" style={{ marginTop: 2 }}>
                  <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
                </svg>
              )}
            </Pressable>
          </View>
          <Text style={styles.subtitle}>Restaurants near you. Green pins have menus shared by other travellers.</Text>
          {status ? <Text accessibilityRole="alert" style={[styles.status, (locationError || searchError) && styles.error]}>{status}</Text> : null}
        </View>
        <View style={styles.mapArea}>
          {active ? (
            <NearbyMap center={center} places={places} selectedId={selected?.google_place_id ?? null} onSelectPlace={openPlace}>
              {fallbackList}
            </NearbyMap>
          ) : null}
        </View>
      </View>
      <PublicMenuSheet
        place={selected}
        attribution={nearby?.attribution ?? ""}
        state={menuState}
        retryDisabled={menuCooling}
        onClose={() => closeSheet()}
        onRetry={() => { if (selectedRef.current) void loadMenus(selectedRef.current); }}
        onScan={scanSelected}
        onChooseAllergens={() => { closeSheet(false); router.push("/profiles/edit"); }}
      />
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  header: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 12 },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 },
  title: { color: colors.ink, fontSize: 30, fontWeight: "800", letterSpacing: -1.1, lineHeight: 36 },
  reload: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  reloadDisabled: { opacity: 0.5 },
  subtitle: { color: colors.muted, fontSize: 14, lineHeight: 21, marginTop: 6 },
  status: { color: colors.ink, fontSize: 13, lineHeight: 19, marginTop: 8 },
  error: { color: colors.error },
  mapArea: { flex: 1, minHeight: 240 },
  list: { gap: 10, alignSelf: "stretch", marginTop: 12 },
  place: { borderWidth: 1.5, borderColor: colors.line, borderRadius: 14, padding: 14, backgroundColor: colors.white },
  placeRow: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  placeName: { flex: 1, color: colors.ink, fontSize: 15, fontWeight: "700", lineHeight: 21 },
  distance: { color: colors.muted, fontSize: 13, paddingTop: 2 },
  badge: { fontSize: 12, fontWeight: "700", marginTop: 6 },
  badgePublic: { color: colors.greenDark },
  badgeGeneral: { color: colors.muted },
  attribution: { color: colors.muted, fontSize: 12 },
});
