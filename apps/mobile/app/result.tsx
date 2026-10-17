import { router, useLocalSearchParams } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import type { MenuAllergen, MenuDish, StaffAnswer } from "../src/api/menus";
import { getMenuAnalysis } from "../src/features/capture/analysis";
import { getSelectedAllergenIds } from "../src/features/profile/selection";
import { getConfirmationResult } from "../src/features/menu-results/confirmationResults";
import { okinawaMenuDemo } from "../src/features/menu-results/demo";
import { applyLocalConfirmations } from "../src/features/menu-results/localConfirmations";
import { colors } from "../src/theme";

// Labels match the API's answer_label; they are used only when the API response is not in this tab.
const answerStyles: Record<StaffAnswer, { label: string; backgroundColor: string; color: string }> = {
  contains: { label: "Contains", backgroundColor: "#FBE7E4", color: "#9D231E" },
  shared_utensils: { label: "Shares cooking utensils (ingredients not confirmed)", backgroundColor: "#FFF1D3", color: "#805300" },
  does_not_contain: { label: "Not an ingredient (cross-contact not confirmed)", backgroundColor: "#E4F3EC", color: "#075E49" },
  unknown: { label: "Unknown", backgroundColor: "#FFFFFF", color: colors.ink },
};

const aiLabels: Record<MenuAllergen["ai"]["status"], string> = {
  explicit_present: "Listed on the menu",
  possible: "May contain (AI estimate)",
  unknown: "Unable to determine",
};

type Row = {
  allergenId: number;
  name: string;
  answer: StaffAnswer;
  label: string;
  ai: MenuAllergen["ai"]["status"];
  recheck: boolean;
};
type ResultView = { name: string; originalName: string; rows: Row[]; confirmedAt: string | null; isPublic: boolean | null };

function fromMenuDish(dish: MenuDish, selectedIds: number[]): ResultView | null {
  const items = selectedIds.map((id) => dish.allergens.find((item) => item.allergen_id === id));
  if (selectedIds.length === 0 || items.some((item) => !item?.current_answer)) return null;
  const rows = items.map((item) => ({
    allergenId: item!.allergen_id,
    name: item!.display_name,
    answer: item!.current_answer!.answer,
    label: answerStyles[item!.current_answer!.answer].label,
    ai: item!.ai.status,
    recheck: item!.notices.ai_staff_mismatch || item!.notices.recheck_current_answer,
  }));
  const dates = items.map((item) => item!.current_answer!.confirmed_at).sort();
  return {
    name: dish.display_name || dish.name,
    originalName: dish.display_name && dish.display_name !== dish.name ? dish.name : "",
    rows,
    confirmedAt: dates.at(-1) ?? null,
    isPublic: null,
  };
}

function loadView(id: string | undefined, dishId: string | undefined, demo: boolean): ResultView | null {
  if (!id || !dishId) return null;
  if (demo) {
    const menu = applyLocalConfirmations(okinawaMenuDemo());
    const dish = menu.menu_id === id ? menu.dishes.find((item) => item.dish_id === dishId) : undefined;
    return dish ? fromMenuDish(dish, [3, 23]) : null;
  }
  const cachedDish = getMenuAnalysis(id)?.dishes.find((item) => item.dish_id === dishId);
  const saved = getConfirmationResult(id, dishId);
  if (saved) {
    return {
      name: saved.dish.display_name,
      originalName: cachedDish && cachedDish.name !== saved.dish.display_name ? cachedDish.name : "",
      rows: saved.dish.allergens.map((item) => ({
        allergenId: item.allergen_id,
        name: item.display_name,
        answer: item.answer,
        label: item.answer_label,
        ai: item.ai.status,
        recheck: item.notices.ai_staff_mismatch || item.notices.recheck_current_answer,
      })),
      confirmedAt: saved.confirmed_at,
      isPublic: saved.is_public,
    };
  }
  // Without the API 6 response in this tab, fall back to this menu's latest answers from API 5.
  return cachedDish ? fromMenuDish(cachedDish, getSelectedAllergenIds()) : null;
}

export default function ResultScreen() {
  const { id, dish_id: dishId, demo } = useLocalSearchParams<{ id?: string; dish_id?: string; demo?: string }>();
  const view = loadView(id, dishId, demo === "okinawa");
  const rows = view?.rows ?? [];
  const contains = rows.filter((item) => item.answer === "contains");
  const recheck = rows.some((item) => item.recheck);
  const result = contains.length
    ? { title: "Staff reported an allergen", description: `Staff answered that ${contains.map((item) => item.name).join(" and ")} ${contains.length === 1 ? "is an ingredient" : "are ingredients"}.`, background: "#FBE7E4", color: "#9D231E" }
    : rows.some((item) => item.answer === "shared_utensils")
      ? { title: "Shared utensils reported", description: "Staff reported shared cooking utensils. Whether it is an ingredient was not confirmed.", background: "#FFF1D3", color: "#805300" }
      : rows.some((item) => item.answer === "unknown")
        ? { title: "Please ask staff again", description: "Staff could not confirm every selected allergen.", background: "#F3F6F4", color: colors.ink }
        : { title: "Staff answers recorded", description: "Staff answered these are not ingredients. Cross-contact was not confirmed.", background: "#E4F3EC", color: "#075E49" };

  const backToMenu = () => router.replace({
    pathname: "/menu",
    params: demo === "okinawa" ? { demo: "okinawa" } : id ? { id } : {},
  });

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.pageContent}>
      <View style={styles.content}>
        {view ? (
          <>
            <Text style={styles.dishName}>{view.name}{view.originalName ? ` ${view.originalName}` : ""}</Text>

            <View style={[styles.resultBanner, { backgroundColor: result.background }]}>
              <Text style={[styles.resultTitle, { color: result.color }]}>{result.title}</Text>
              <Text style={[styles.resultDescription, { color: result.color }]}>{result.description}</Text>
            </View>

            <View style={styles.tableHeader}>
              <Text style={styles.columnHeading}>Your allergen</Text>
              <Text style={styles.columnHeading}>Staff answer</Text>
            </View>
            <View style={styles.answerTable}>
              {rows.map((item, index) => {
                const appearance = answerStyles[item.answer];
                return (
                  <View key={item.allergenId} style={[styles.answerRow, index > 0 && styles.rowDivider]}>
                    <View style={styles.allergenCopy}>
                      <Text style={styles.allergenName}>{item.name}</Text>
                      <Text style={styles.aiEstimate}>AI estimate: {aiLabels[item.ai]}</Text>
                    </View>
                    <Text style={[styles.answerBadge, { backgroundColor: appearance.backgroundColor, color: appearance.color }]}>{item.label}</Text>
                  </View>
                );
              })}
            </View>
            {recheck ? <Text style={styles.recheck}>The menu and the staff answer differ, or staff could not confirm. Please ask again.</Text> : null}
            {view.confirmedAt ? <Text style={styles.note}>Answered {new Date(view.confirmedAt).toLocaleString("en")}. Staff answers were entered on this phone and are not verified.</Text> : null}
            {view.isPublic === true ? <Text style={styles.note}>This menu and the staff answers will be shared on the map.</Text> : null}
            {view.isPublic === false ? <Text style={styles.note}>These answers are not shared publicly.</Text> : null}
          </>
        ) : (
          <Text accessibilityRole="alert" style={styles.unavailable}>This confirmation is not available in this tab.</Text>
        )}
      </View>

      <Pressable accessibilityRole="button" onPress={backToMenu} style={styles.backButton}>
        <Text style={styles.backText}>Back to menu</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  pageContent: { flexGrow: 1, paddingHorizontal: 20, paddingTop: 24, paddingBottom: 26 },
  content: { flexGrow: 1, justifyContent: "center", paddingVertical: 24 },
  dishName: { color: colors.ink, fontSize: 25, lineHeight: 32, fontWeight: "800", marginBottom: 26 },
  resultBanner: { borderRadius: 18, padding: 20, marginBottom: 32 },
  resultTitle: { fontSize: 21, lineHeight: 27, fontWeight: "800" },
  resultDescription: { fontSize: 14, lineHeight: 21, marginTop: 6 },
  tableHeader: { flexDirection: "row", paddingHorizontal: 14, marginBottom: 9 },
  columnHeading: { flex: 1, color: colors.muted, fontSize: 13 },
  answerTable: { borderWidth: 1.5, borderColor: colors.line, borderRadius: 18, overflow: "hidden" },
  answerRow: { flexDirection: "row", minHeight: 62, alignItems: "center", paddingHorizontal: 14, paddingVertical: 10, gap: 8 },
  rowDivider: { borderTopWidth: 1, borderTopColor: colors.line },
  allergenCopy: { flex: 1 },
  allergenName: { color: colors.ink, fontSize: 17, fontWeight: "700" },
  aiEstimate: { color: colors.muted, fontSize: 12, marginTop: 3 },
  answerBadge: { fontSize: 13, fontWeight: "700", borderRadius: 14, overflow: "hidden", paddingHorizontal: 10, paddingVertical: 5, textAlign: "center", flexShrink: 1, maxWidth: "55%" },
  recheck: { color: "#805300", fontSize: 13, lineHeight: 19, marginTop: 18 },
  note: { color: colors.muted, fontSize: 12, lineHeight: 18, marginTop: 12 },
  unavailable: { color: colors.muted, fontSize: 15, textAlign: "center" },
  backButton: { minHeight: 54, borderRadius: 28, backgroundColor: colors.green, alignItems: "center", justifyContent: "center" },
  backText: { color: colors.white, fontSize: 16, fontWeight: "800" },
});
