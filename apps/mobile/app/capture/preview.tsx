import { useCallback, useState } from "react";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { analyzeMenu } from "../../src/api/menus";
import { ApiError, clearAccountSession } from "../../src/api/auth";
import { Page } from "../../src/components/Page";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { useCapture } from "../../src/features/capture/CaptureContext";
import { saveMenuAnalysis } from "../../src/features/capture/analysis";
import { getSelectedAllergenIds } from "../../src/features/profile/selection";
import { rememberedPlaceName } from "../../src/features/places/placeMemory";
import { colors } from "../../src/theme";

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return "Analysis failed. Please try again.";
  if (error.code === "api_not_configured") return "The analysis API is not connected yet. No photo was uploaded.";
  if (error.code === "login_required") return "Log in before analyzing a menu.";
  if (error.status === 401) return "Your login expired. Log in again before analyzing.";
  if (error.code === "timeout") return "Analysis took too long. Please try again.";
  if (error.status === 404) return "The selected restaurant could not be found. Retake, then change the restaurant or skip.";
  if (error.status === 413 || error.status === 415) return "This image cannot be uploaded. Choose a smaller JPEG or PNG photo.";
  if (error.status === 422) return "The menu could not be read. Retake a clearer photo.";
  if (error.status === 429) return "Too many requests. Please wait before trying again.";
  if (error.status === 502 || error.status === 503 || error.status === 504) return "Analysis is unavailable right now. Please try again.";
  return error.message;
}

export default function CapturePreviewScreen() {
  const { google_place_id: placeId } = useLocalSearchParams<{ google_place_id?: string }>();
  const { image, clearImage } = useCapture();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [needsLogin, setNeedsLogin] = useState(false);
  const captureRoute = { pathname: "/capture" as const, params: { google_place_id: placeId || "" } };

  useFocusEffect(useCallback(() => () => clearImage(), []));

  async function analyze() {
    if (!image || busy) return;
    const ids = getSelectedAllergenIds();
    if (ids.length === 0) {
      setError("Select at least one allergen in your profile first.");
      return;
    }
    setBusy(true);
    setError("");
    setNeedsLogin(false);
    try {
      const result = await analyzeMenu(image.file, ids, placeId);
      saveMenuAnalysis(result);
      clearImage();
      router.replace({ pathname: "/menu", params: { id: result.menu_id } });
    } catch (cause) {
      // An invalid account token is never retried as a guest; the user logs in again instead.
      if (cause instanceof ApiError && cause.status === 401) {
        if (cause.code !== "login_required") clearAccountSession();
        setNeedsLogin(true);
      }
      setError(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }

  if (!image) {
    return (
      <Page title="No photo to review" subtitle="Take or choose a menu photo first.">
        <PrimaryButton label="Open camera" onPress={() => router.replace(captureRoute)} />
      </Page>
    );
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.pageContent}>
      <Text style={styles.title}>Analyze this photo?</Text>
      <Text style={styles.subtitle}>{placeId ? rememberedPlaceName(placeId) : "No restaurant selected"} · Check the menu text is sharp and readable.</Text>
      <View style={styles.photoFrame}>
        <Image source={{ uri: image.url }} resizeMode="contain" style={styles.photo} accessibilityLabel="Photo of the menu to analyze" />
      </View>
      {!placeId ? <Text style={styles.note}>Previous staff answers are not used without a restaurant.</Text> : null}
      {busy ? <Text accessibilityRole="alert" style={styles.progress}>Analyzing menu… This may take up to 45 seconds.</Text> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {needsLogin ? (
        <Pressable accessibilityRole="button" onPress={() => router.push("/login")}><Text style={styles.login}>Log in</Text></Pressable>
      ) : null}
      <View style={styles.actions}>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled: busy }}
          disabled={busy}
          onPress={() => { clearImage(); router.replace(captureRoute); }}
          style={[styles.action, styles.retake, busy && styles.disabled]}
        ><Text style={styles.retakeText}>↻ Retake</Text></Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled: busy }}
          disabled={busy}
          onPress={() => { void analyze(); }}
          style={[styles.action, styles.analyze, busy && styles.disabled]}
        ><Text style={styles.analyzeText}>{busy ? "Analyzing…" : "✓ Analyze"}</Text></Pressable>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  pageContent: { flexGrow: 1, paddingHorizontal: 24, paddingTop: 24, paddingBottom: 28 },
  title: { color: colors.ink, fontSize: 28, fontWeight: "800", lineHeight: 34 },
  subtitle: { color: colors.muted, fontSize: 14, lineHeight: 21, marginTop: 8, marginBottom: 20 },
  photoFrame: { width: "100%", aspectRatio: 0.72, maxHeight: 590, borderRadius: 16, overflow: "hidden", backgroundColor: "#17231F", justifyContent: "center" },
  photo: { width: "100%", height: "100%" },
  note: { marginTop: 10, color: colors.muted, fontSize: 12, lineHeight: 18 },
  actions: { flexDirection: "row", gap: 12, marginTop: 26 },
  action: { flex: 1, minHeight: 54, borderRadius: 28, alignItems: "center", justifyContent: "center" },
  retake: { backgroundColor: colors.white, borderWidth: 1.5, borderColor: colors.green },
  analyze: { backgroundColor: colors.green },
  retakeText: { color: colors.green, fontSize: 15, fontWeight: "700" },
  analyzeText: { color: colors.white, fontSize: 15, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  progress: { color: colors.greenDark, marginTop: 15 },
  error: { color: "#B42318", marginTop: 15, lineHeight: 20 },
  login: { color: colors.green, fontWeight: "700", marginTop: 8, paddingVertical: 4 },
});
