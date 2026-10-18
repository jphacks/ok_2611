import { useCallback, useRef, useState } from "react";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { ApiError } from "../../src/api/client";
import { getNearbyPlaces, nearbySearchRadiusM, type NearbyPlaces } from "../../src/api/places";
import { hasActiveAccountSession } from "../../src/api/auth";
import { Page } from "../../src/components/Page";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { useCapture } from "../../src/features/capture/CaptureContext";
import { getCurrentCoordinates } from "../../src/features/places/location";
import { forgetPlace, getRememberedPlace, isPlaceId, rememberPlace } from "../../src/features/places/placeMemory";
import { colors } from "../../src/theme";

type Candidate = { google_place_id: string; name: string; attribution: string };
type SearchState = "locating" | "searching" | "ready" | "error";

function searchError(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.status === 429) return "Too many searches. Wait a minute before trying again, or skip.";
    if (cause.status === 503) return "Restaurant search is unavailable right now. Try again or skip.";
    if (cause.code === "timeout") return "Restaurant search took too long. Try again or skip.";
    return "Could not load nearby restaurants. Try again or skip.";
  }
  return cause instanceof Error ? cause.message : "Your location is unavailable. Try again or skip.";
}

export default function PlaceSelectScreen() {
  const { google_place_id: placeId } = useLocalSearchParams<{ google_place_id?: string }>();
  const { clearImage } = useCapture();
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [result, setResult] = useState<NearbyPlaces | null>(null);
  const [state, setState] = useState<SearchState>("ready");
  const [error, setError] = useState("");
  const activeRequest = useRef<AbortController | null>(null);
  const leaving = useRef(false);

  const search = useCallback(async () => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setSelected(null);
    setResult(null);
    setError("");
    setState("locating");
    try {
      const coordinates = await getCurrentCoordinates(controller.signal);
      if (controller.signal.aborted) return;
      setState("searching");
      const nearby = await getNearbyPlaces(coordinates.latitude, coordinates.longitude, controller.signal);
      if (controller.signal.aborted) return;
      setResult(nearby);
      setState("ready");
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(searchError(cause));
      setState("error");
    }
  }, []);

  useFocusEffect(useCallback(() => {
    leaving.current = false;
    // Do not request location behind the layout's login cover.
    if (!hasActiveAccountSession()) return;
    setSelected(null);
    setResult(null);
    setError("");
    setState("ready");
    if (isPlaceId(placeId)) {
      // A candidate handed over from ⑥ or an earlier choice. Its name lives in memory only; after a reload it is unknown.
      setSelected(getRememberedPlace(placeId) ?? { google_place_id: placeId, name: "Selected restaurant", attribution: "" });
    } else {
      void search();
    }
    return () => activeRequest.current?.abort();
  }, [placeId, search]));

  function continueToCapture(candidate: Candidate | null) {
    if (leaving.current) return;
    leaving.current = true;
    activeRequest.current?.abort();
    clearImage();
    if (candidate) rememberPlace(candidate);
    else forgetPlace();
    // An empty param explicitly removes a previously selected restaurant on Skip.
    router.push({ pathname: "/capture", params: { google_place_id: candidate?.google_place_id ?? "" } });
  }

  const busy = state === "locating" || state === "searching";
  return (
    <Page title="Choose a restaurant" subtitle="Select where you are dining, then confirm to scan your menu.">
      <Text style={styles.hint}>If you skip, your scan will not be linked to a restaurant. Previous staff answers will not be used.</Text>
      <View style={styles.actions}>
        <View style={styles.action}><PrimaryButton label="Skip" secondary onPress={() => continueToCapture(null)} /></View>
        <View style={styles.action}><PrimaryButton label="Confirm" disabled={!selected} onPress={() => { if (selected) continueToCapture(selected); }} /></View>
      </View>
      {busy ? <View style={styles.loading} accessibilityRole="status">
        <ActivityIndicator color={colors.green} />
        <Text style={styles.hint}>{state === "locating" ? "Finding your location…" : "Finding nearby restaurants…"}</Text>
      </View> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {result ? <>
        <Text style={styles.section}>Nearby restaurants · within {nearbySearchRadiusM} m</Text>
        {result.places.length === 0 ? <Text style={styles.hint}>No nearby restaurants found. Try again or skip to scan a menu.</Text> : null}
        <View accessibilityRole="radiogroup" accessibilityLabel="Nearby restaurants" style={styles.list}>
          {result.places.map((place) => {
            const checked = selected?.google_place_id === place.google_place_id;
            return <Pressable key={place.google_place_id} accessibilityRole="radio" accessibilityState={{ checked }}
              accessibilityLabel={`${place.name}, ${place.distance_m} metres away, ${place.address}`}
              onPress={() => setSelected({ ...place, attribution: result.attribution })} style={[styles.candidate, checked && styles.selected]}>
              <View style={styles.row}>
                <Text style={styles.name}>{place.name}</Text>
                <Text style={styles.distance}>{place.distance_m} m</Text>
              </View>
              {place.address ? <Text style={styles.address}>{place.address}</Text> : null}
              <Text style={styles.selection}>{checked ? "Selected · Confirm above to continue" : "Select restaurant"}</Text>
            </Pressable>;
          })}
        </View>
        <Text style={styles.attribution}>{result.attribution}</Text>
      </> : selected ? <View style={[styles.candidate, styles.selected]}>
        <Text style={styles.name}>{selected.name}</Text>
        <Text style={styles.selection}>Confirm above if you are at this restaurant.</Text>
        {selected.attribution ? <Text style={styles.attribution}>{selected.attribution}</Text> : null}
      </View> : null}
      <View style={styles.retry}><PrimaryButton label={state === "error" ? "Try again" : "Find nearby restaurants"} secondary disabled={busy} onPress={() => { void search(); }} /></View>
    </Page>
  );
}

const styles = StyleSheet.create({
  hint: { color: colors.muted, fontSize: 13, lineHeight: 20 },
  actions: { flexDirection: "row", gap: 12, marginTop: 20, marginBottom: 24 },
  action: { flex: 1 },
  loading: { flexDirection: "row", gap: 10, alignItems: "center", paddingVertical: 12 },
  error: { color: colors.error, fontSize: 14, lineHeight: 21, marginBottom: 16 },
  section: { color: colors.ink, fontSize: 14, fontWeight: "700", marginBottom: 12 },
  list: { gap: 12 },
  candidate: { borderWidth: 1.5, borderColor: colors.line, borderRadius: 15, padding: 16 },
  selected: { borderColor: colors.green, backgroundColor: colors.greenPale },
  row: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  name: { flex: 1, color: colors.ink, fontSize: 16, fontWeight: "700", lineHeight: 22 },
  distance: { color: colors.muted, fontSize: 13, paddingTop: 2 },
  address: { color: colors.muted, fontSize: 13, lineHeight: 19, marginTop: 6 },
  selection: { color: colors.greenDark, fontSize: 12, lineHeight: 18, marginTop: 10 },
  attribution: { color: colors.muted, fontSize: 12, marginTop: 14 },
  retry: { marginTop: 20 },
});
