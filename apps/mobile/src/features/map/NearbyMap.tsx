import { createElement, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import type { NearbyPlace } from "../../api/places";
import { colors } from "../../theme";
import {
  isMapConfigured, loadGoogleMaps, MapLoadError, mapId, mapLoadMessage, onMapAuthFailure,
  type GoogleMap, type GoogleMapsLibraries, type GoogleMarker, type LatLng, type MapLoadFailure,
} from "./googleMaps";

type Props = {
  // The search centre: the user's last acquired location. Panning the map never changes it.
  center: LatLng | null;
  places: NearbyPlace[];
  selectedId: string | null;
  onSelectPlace: (place: NearbyPlace) => void;
  // Rendered under the message only while the map cannot be shown.
  children?: ReactNode;
};
type LoadState = { status: "loading" } | { status: "ready" } | { status: "error"; reason: MapLoadFailure };
type PinEntry = { marker: GoogleMarker; element: HTMLDivElement; listener: () => void; place: NearbyPlace };

const publicColor = colors.green;
const generalColor = "#5E6E67";

export function pinLabel(place: NearbyPlace): string {
  const shared = place.has_public_menus
    ? `${place.public_menu_count === 1 ? "1 shared dish" : `${place.public_menu_count} shared dishes`}`
    : "no shared menus yet";
  return `${place.name}, ${shared}`;
}

// Public restaurants get a filled green pin with the dish count; others a hollow grey pin. Colour is not the only cue.
function stylePin(element: HTMLDivElement, place: NearbyPlace, selected: boolean): void {
  const shared = place.has_public_menus;
  element.textContent = shared ? String(place.public_menu_count) : "";
  Object.assign(element.style, {
    boxSizing: "border-box", display: "flex", alignItems: "center", justifyContent: "center",
    minWidth: shared ? "30px" : "20px", height: shared ? "30px" : "20px", padding: shared ? "0 7px" : "0",
    borderRadius: "999px", fontFamily: "-apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif",
    fontSize: "13px", fontWeight: "800", color: colors.white,
    background: shared ? publicColor : colors.white,
    border: shared ? `2px solid ${colors.white}` : `3px solid ${generalColor}`,
    boxShadow: selected ? `0 0 0 4px ${colors.ink}` : "0 1px 4px rgba(0,0,0,0.35)",
    transform: selected ? "scale(1.2)" : "none", cursor: "pointer",
  });
}

function locationDot(): HTMLDivElement {
  const element = document.createElement("div");
  Object.assign(element.style, {
    width: "18px", height: "18px", borderRadius: "50%", background: "#1A73E8", border: "3px solid #FFFFFF",
    boxShadow: "0 0 0 6px rgba(26,115,232,0.22)", boxSizing: "border-box", pointerEvents: "none",
  });
  return element;
}

function ensureLocationMarkerStyle(): void {
  if (document.getElementById("meelyze-location-marker-style")) return;
  const style = document.createElement("style");
  style.id = "meelyze-location-marker-style";
  style.textContent = "[data-meelyze-location]{pointer-events:none !important}";
  document.head.appendChild(style);
}

const toLatLng = (place: NearbyPlace): LatLng => ({ lat: place.latitude, lng: place.longitude });

export function NearbyMap({ center, places, selectedId, onSelectPlace, children }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const librariesRef = useRef<GoogleMapsLibraries | null>(null);
  const mapRef = useRef<GoogleMap | null>(null);
  const pinsRef = useRef(new Map<string, PinEntry>());
  const locationMarkerRef = useRef<GoogleMarker | null>(null);
  const onSelectRef = useRef(onSelectPlace);
  onSelectRef.current = onSelectPlace;
  const [load, setLoad] = useState<LoadState>(isMapConfigured ? { status: "loading" } : { status: "error", reason: "not_configured" });
  const [mapReady, setMapReady] = useState(false);

  const startLoad = useCallback(() => {
    if (!isMapConfigured) return () => undefined;
    let alive = true;
    setLoad({ status: "loading" });
    loadGoogleMaps().then(
      (libraries) => { if (alive) { librariesRef.current = libraries; setLoad({ status: "ready" }); } },
      (cause) => { if (alive) setLoad({ status: "error", reason: cause instanceof MapLoadError ? cause.reason : "load_failed" }); },
    );
    return () => { alive = false; };
  }, []);

  useEffect(() => startLoad(), [startLoad]);
  useEffect(() => onMapAuthFailure(() => setLoad({ status: "error", reason: "auth_failed" })), []);

  // One map instance per screen. It is created after the first location fix and kept across sheet open/close.
  useEffect(() => {
    const libraries = librariesRef.current;
    if (load.status !== "ready" || !libraries || !center || !containerRef.current || mapRef.current) return;
    // Zoom 15 keeps the 500 m search radius inside the frame. Only the zoom buttons are shown.
    mapRef.current = new libraries.Map(containerRef.current, {
      center, zoom: 15, mapId, disableDefaultUI: true, zoomControl: true, cameraControl: false, streetViewControl: false,
      clickableIcons: false, gestureHandling: "greedy", keyboardShortcuts: true,
    });
    setMapReady(true);
  }, [load.status, center]);

  // The current-location marker follows the search centre and is not clickable.
  useEffect(() => {
    const libraries = librariesRef.current;
    const map = mapRef.current;
    if (!mapReady || !libraries || !map) return;
    if (!center) {
      if (locationMarkerRef.current) locationMarkerRef.current.map = null;
      locationMarkerRef.current = null;
      return;
    }
    if (!locationMarkerRef.current) {
      locationMarkerRef.current = new libraries.AdvancedMarkerElement({ map, position: center, title: "Your location", content: locationDot(), zIndex: 1000 });
      // Drawn on top but never takes taps, so a restaurant right at the user's position stays selectable.
      // Google rewrites the marker's inline style, so a stylesheet rule with !important is used instead.
      locationMarkerRef.current.setAttribute("data-meelyze-location", "");
      ensureLocationMarkerStyle();
    } else {
      locationMarkerRef.current.position = center;
      locationMarkerRef.current.map = map;
    }
    map.panTo(center);
  }, [mapReady, center]);

  // Diff pins by Place ID so a re-search removes stale pins and their listeners without duplicating any.
  useEffect(() => {
    const libraries = librariesRef.current;
    const map = mapRef.current;
    const pins = pinsRef.current;
    if (!mapReady || !libraries || !map) return;
    const next = new Map(places.map((place) => [place.google_place_id, place]));
    for (const [id, entry] of pins) {
      if (next.has(id)) continue;
      entry.marker.removeEventListener("gmp-click", entry.listener);
      entry.marker.map = null;
      pins.delete(id);
    }
    for (const place of places) {
      const existing = pins.get(place.google_place_id);
      if (existing) {
        existing.place = place;
        existing.marker.position = toLatLng(place);
        existing.marker.title = pinLabel(place);
        stylePin(existing.element, place, place.google_place_id === selectedId);
        continue;
      }
      const element = document.createElement("div");
      stylePin(element, place, place.google_place_id === selectedId);
      const marker = new libraries.AdvancedMarkerElement({
        map, position: toLatLng(place), title: pinLabel(place), content: element, gmpClickable: true,
        zIndex: place.has_public_menus ? 2 : 1,
      });
      const entry: PinEntry = { marker, element, place, listener: () => onSelectRef.current(entry.place) };
      marker.addEventListener("gmp-click", entry.listener);
      pins.set(place.google_place_id, entry);
    }
  }, [mapReady, places, selectedId]);

  // Leaving the screen removes every marker and listener.
  useEffect(() => () => {
    for (const entry of pinsRef.current.values()) {
      entry.marker.removeEventListener("gmp-click", entry.listener);
      entry.marker.map = null;
    }
    pinsRef.current.clear();
    if (locationMarkerRef.current) locationMarkerRef.current.map = null;
    locationMarkerRef.current = null;
    mapRef.current = null;
  }, []);

  const showMap = load.status === "ready" && center !== null;
  return (
    <View style={styles.frame}>
      {createElement("div", {
        ref: containerRef,
        "aria-label": "Map of nearby restaurants",
        style: { position: "absolute", inset: 0, visibility: showMap ? "visible" : "hidden" },
      })}
      {!showMap ? (
        <ScrollView style={styles.placeholderScroll} contentContainerStyle={styles.placeholder}>
          {load.status === "loading" ? <ActivityIndicator color={colors.green} /> : null}
          <Text style={styles.placeholderText}>
            {load.status === "error" ? mapLoadMessage(load.reason)
              : load.status === "loading" ? "Loading the map…"
                : "Current location is unavailable, so the map is not shown."}
          </Text>
          {load.status === "error" && load.reason !== "not_configured" && load.reason !== "auth_failed" ? (
            <Pressable accessibilityRole="button" onPress={() => { startLoad(); }} style={styles.retry}>
              <Text style={styles.retryText}>Retry map</Text>
            </Pressable>
          ) : null}
          {children}
        </ScrollView>
      ) : (
        <>
          <View style={styles.legend} pointerEvents="none">
            <View style={styles.legendRow}><View style={[styles.legendDot, styles.legendPublic]}><Text style={styles.legendCount}>2</Text></View><Text style={styles.legendText}>Shared menus</Text></View>
            <View style={styles.legendRow}><View style={[styles.legendDot, styles.legendGeneral]} /><Text style={styles.legendText}>No shared menus yet</Text></View>
          </View>
          <Pressable accessibilityRole="button" accessibilityLabel="Back to my location" onPress={() => { if (center) mapRef.current?.panTo(center); }} style={styles.recenter}>
            <Text style={styles.recenterText}>◎</Text>
          </Pressable>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { flex: 1, overflow: "hidden", backgroundColor: "#E8EFEB", position: "relative" },
  placeholderScroll: { flex: 1 },
  placeholder: { flexGrow: 1, alignItems: "center", justifyContent: "center", gap: 12, padding: 20 },
  placeholderText: { color: colors.muted, fontSize: 14, lineHeight: 21, textAlign: "center" },
  retry: { borderWidth: 1.5, borderColor: colors.green, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 8, backgroundColor: colors.white },
  retryText: { color: colors.greenDark, fontWeight: "700" },
  legend: { position: "absolute", top: 10, left: 10, gap: 4, backgroundColor: "rgba(255,255,255,0.94)", borderRadius: 10, paddingHorizontal: 9, paddingVertical: 7 },
  legendRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  legendDot: { width: 18, height: 18, borderRadius: 9, alignItems: "center", justifyContent: "center" },
  legendPublic: { backgroundColor: publicColor },
  legendGeneral: { backgroundColor: colors.white, borderWidth: 3, borderColor: generalColor, width: 14, height: 14, marginHorizontal: 2 },
  legendCount: { color: colors.white, fontSize: 10, fontWeight: "800" },
  legendText: { color: colors.ink, fontSize: 11, fontWeight: "600" },
  recenter: { position: "absolute", top: 10, right: 10, width: 44, height: 44, borderRadius: 22, backgroundColor: colors.white, alignItems: "center", justifyContent: "center", shadowColor: "#000", shadowOpacity: 0.25, shadowRadius: 4, shadowOffset: { width: 0, height: 1 } },
  recenterText: { color: "#1A73E8", fontSize: 22, lineHeight: 24 },
});
