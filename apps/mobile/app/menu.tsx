import { useEffect, useRef, useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { getMenuResult, isMenuResultConfigured } from "../src/api/menus";
import { getMenuAnalysis } from "../src/features/capture/analysis";
import { okinawaMenuDemo } from "../src/features/menu-results/demo";
import { applyLocalConfirmations } from "../src/features/menu-results/localConfirmations";
import { getSelectedAllergenIds } from "../src/features/profile/selection";
import type { MenuSummary, SummaryDish, BadgeTone } from "../src/features/menu-results/summary";
import { DishDetailSheet } from "../src/features/menu-results/DishDetailSheet";
import { colors } from "../src/theme";

const tones: Record<BadgeTone, { backgroundColor: string; color: string; borderColor: string }> = {
  danger: { backgroundColor: "#FBE7E4", color: "#9D231E", borderColor: "#FBE7E4" },
  caution: { backgroundColor: "#FFF1D3", color: "#805300", borderColor: "#FFF1D3" },
  unknown: { backgroundColor: "#FFFFFF", color: colors.ink, borderColor: "#B8C8BF" },
  reportedAbsent: { backgroundColor: "#E4F3EC", color: "#075E49", borderColor: "#E4F3EC" },
};

function DishCard({ dish, confirmed, disabled, onPress }: { dish: SummaryDish; confirmed: boolean; disabled: boolean; onPress: () => void }) {
  const price = dish.price == null ? "" : `${dish.currency === "JPY" ? "¥" : `${dish.currency} `}${dish.price}`;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${confirmed ? "View confirmed result" : "View details"} for ${dish.name}`} disabled={disabled} onPress={onPress} style={[styles.dishCard, confirmed && styles.confirmedCard]}>
      <View style={styles.dishTop}>
        <Text style={styles.dishName}>{dish.name}{dish.originalName ? ` ${dish.originalName}` : ""}</Text>
        {price ? <Text style={styles.price}>{price}</Text> : null}
      </View>
      <View style={styles.badges}>
        {dish.badges.map((badge, index) => {
          const tone = tones[badge.tone];
          return <Text key={`${index}-${badge.label}`} style={[styles.badge, { backgroundColor: tone.backgroundColor, color: tone.color, borderColor: tone.borderColor }]}>{badge.label}</Text>;
        })}
      </View>
      {dish.needsRecheck ? <Text style={styles.recheck}>Answers or evidence need rechecking with staff.</Text> : null}
    </Pressable>
  );
}

export default function MenuScreen() {
  const { id, demo } = useLocalSearchParams<{ id?: string; demo?: string }>();
  const demoMode = demo === "okinawa" || demo === "wheat-pork" || demo === "wheat-pork-confirmed" ? "okinawa" : null;
  const [summary, setSummary] = useState<MenuSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedDishId, setSelectedDishId] = useState<string | null>(null);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectedDetail = selectedDishId ? summary?.details[selectedDishId] ?? null : null;

  useEffect(() => () => {
    if (dismissTimer.current) clearTimeout(dismissTimer.current);
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      setSummary(null);
      setError("");
      if (!demoMode && !id) return;
      setLoading(true);
      try {
        let response: Response;
        if (demoMode) {
          response = await fetch("/menu-summary", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ menu: applyLocalConfirmations(okinawaMenuDemo()), selectedAllergenIds: [3, 23] }),
          });
        } else {
          const analysis = getMenuAnalysis(id!);
          if (!analysis) throw new Error("This menu result is not available in this tab.");
          const selectedAllergenIds = getSelectedAllergenIds();
          if (selectedAllergenIds.length === 0) throw new Error("Choose your allergens before viewing a menu.");
          const menu = isMenuResultConfigured
            ? await getMenuResult(analysis.menu_id, analysis.analysis_token, selectedAllergenIds)
            : analysis;
          const { analysis_token: _token, ...cachedMenu } = analysis;
          response = await fetch("/menu-summary", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ menu: applyLocalConfirmations(isMenuResultConfigured ? menu : cachedMenu), selectedAllergenIds }),
          });
        }
        if (!response.ok) throw new Error("Could not prepare the menu list.");
        const result: unknown = await response.json();
        if (!result || typeof result !== "object" || !("summary" in result)) throw new Error("The menu list response was incomplete.");
        if (active) setSummary((result as { summary: MenuSummary }).summary);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "Could not open the menu list.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [id, demoMode]);

  const openDemo = () => router.replace({ pathname: "/menu", params: { demo: "okinawa" } });
  const closeSheet = () => {
    if (dismissTimer.current) return;
    // Keep the modal mounted until the tap finishes so it cannot activate a card underneath.
    dismissTimer.current = setTimeout(() => {
      dismissTimer.current = null;
      setSelectedDishId(null);
    }, 180);
  };
  const askStaff = () => {
    if (!summary || !selectedDetail || dismissTimer.current) return;
    const menuId = summary.menuId;
    const dishId = selectedDetail.dishId;
    dismissTimer.current = setTimeout(() => {
      dismissTimer.current = null;
      setSelectedDishId(null);
      router.push({ pathname: "/confirm", params: {
        id: menuId,
        dish_id: dishId,
        ...(demoMode ? { demo: "okinawa" } : {}),
      } });
    }, 180);
  };
  return (
    <>
    <ScrollView style={styles.screen} contentContainerStyle={styles.pageContent}>
      <View style={styles.heading}>
        <View style={styles.headingCopy}>
          <Text style={styles.title}>Analysis complete</Text>
          <Text style={styles.subtitle}>{demoMode ? "Okinawa menu · Wheat + Pork" : "Menu analysis"}</Text>
        </View>
        <Pressable accessibilityRole="button" style={styles.retake} onPress={() => router.push("/capture")}>
          <Text style={styles.retakeText}>↻ Retake</Text>
        </Pressable>
      </View>

      {demoMode ? (
        <View style={styles.previewControls}>
          <Text style={styles.previewNote}>Local result from the supplied Okinawa menu test fixture. Staff answers in this preview stay in this browser tab; no production API or database is used.</Text>
        </View>
      ) : null}

      <Text style={styles.safety}>Estimates only. Always confirm with restaurant staff.</Text>
      {loading ? <Text style={styles.message}>Preparing menu list…</Text> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {!id && !demoMode ? (
        <View style={styles.empty}>
          <Text style={styles.message}>Scan a menu to view its analysis.</Text>
          <Pressable accessibilityRole="button" onPress={openDemo}><Text style={styles.previewLink}>Open Okinawa menu preview</Text></Pressable>
        </View>
      ) : null}

      {summary?.confirmed.length ? (
        <View style={styles.section}>
          <View style={styles.sectionRow}><Text style={styles.sectionTitle}>✓ CONFIRMED BY STAFF</Text><Text style={styles.sectionHint}>{summary.confirmed.length} {summary.confirmed.length === 1 ? "dish" : "dishes"}</Text></View>
          {summary.confirmed.map((dish) => <DishCard key={dish.dishId} dish={dish} confirmed disabled={selectedDishId !== null} onPress={() => router.push({
            pathname: "/result",
            params: { id: summary.menuId, dish_id: dish.dishId, ...(demoMode ? { demo: "okinawa" } : {}) },
          })} />)}
        </View>
      ) : null}

      {summary ? (
        <View style={styles.section}>
          <View style={styles.sectionRow}><Text style={styles.sectionTitle}>AI ESTIMATE · {summary.estimates.length} DISHES</Text><Text style={styles.sectionHint}>Ask staff for details</Text></View>
          {summary.estimates.map((dish) => <DishCard key={dish.dishId} dish={dish} confirmed={false} disabled={selectedDishId !== null} onPress={() => setSelectedDishId(dish.dishId)} />)}
        </View>
      ) : null}

      <View style={styles.spacer} />
      <View style={styles.tabBar}>
        <Pressable accessibilityRole="button" onPress={() => router.push("/map")}><Text style={styles.tab}>⌖{"\n"}Map</Text></Pressable>
        <Pressable accessibilityRole="button" onPress={() => router.push("/capture")}><Text style={[styles.tab, styles.activeTab]}>▣{"\n"}Scan</Text></Pressable>
        <Pressable accessibilityRole="button" onPress={() => router.push("/profiles")}><Text style={styles.tab}>●{"\n"}Profile</Text></Pressable>
      </View>
    </ScrollView>
    <DishDetailSheet detail={selectedDetail} onClose={closeSheet} onAskStaff={askStaff} />
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  pageContent: { flexGrow: 1, paddingTop: 24, paddingHorizontal: 20 },
  heading: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  headingCopy: { flex: 1 },
  title: { color: colors.ink, fontSize: 27, fontWeight: "800", lineHeight: 32 },
  subtitle: { color: colors.muted, fontSize: 13, marginTop: 2 },
  retake: { borderColor: colors.green, borderWidth: 1.5, borderRadius: 24, paddingVertical: 12, paddingHorizontal: 15 },
  retakeText: { color: colors.green, fontWeight: "700" },
  safety: { color: colors.muted, backgroundColor: "#F3F6F4", borderRadius: 10, padding: 11, marginTop: 20, fontSize: 13, lineHeight: 18 },
  previewControls: { marginTop: 14, padding: 12, backgroundColor: "#EDF5F1", borderRadius: 10 },
  previewNote: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  previewLink: { color: colors.green, fontWeight: "700", marginTop: 8, textDecorationLine: "underline" },
  section: { marginTop: 30 },
  sectionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end", gap: 8, marginBottom: 12 },
  sectionTitle: { color: colors.muted, fontSize: 13, fontWeight: "800", flex: 1 },
  sectionHint: { color: colors.muted, fontSize: 12 },
  dishCard: { borderWidth: 2, borderColor: colors.line, borderRadius: 18, padding: 13, marginBottom: 10, backgroundColor: colors.white },
  confirmedCard: { borderColor: "#005C4B", backgroundColor: "#F1F9F5" },
  dishTop: { flexDirection: "row", justifyContent: "space-between", gap: 8 },
  dishName: { color: colors.ink, fontSize: 15, lineHeight: 20, fontWeight: "700", flex: 1 },
  price: { color: colors.ink, fontSize: 14, marginTop: 2 },
  badges: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 8 },
  badge: { borderWidth: 1, borderRadius: 12, paddingHorizontal: 8, paddingVertical: 3, fontSize: 12, fontWeight: "700", overflow: "hidden" },
  recheck: { color: "#805300", fontSize: 11, marginTop: 8 },
  message: { color: colors.muted, marginTop: 22 },
  error: { color: colors.error, marginTop: 22 },
  empty: { alignItems: "flex-start" },
  spacer: { flexGrow: 1, minHeight: 28 },
  tabBar: { flexDirection: "row", justifyContent: "space-around", borderTopWidth: 1, borderColor: colors.line, paddingTop: 16, paddingBottom: 25, marginHorizontal: -20 },
  tab: { color: colors.muted, fontSize: 12, textAlign: "center", lineHeight: 20 },
  activeTab: { color: colors.green, fontWeight: "700" },
});
