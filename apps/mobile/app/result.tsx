import { router, useLocalSearchParams } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { getMenuAnalysis } from "../src/features/capture/analysis";
import { getSelectedAllergenIds } from "../src/features/profile/selection";
import { okinawaMenuDemo } from "../src/features/menu-results/demo";
import { applyLocalConfirmations, type StaffAnswer } from "../src/features/menu-results/localConfirmations";
import { colors } from "../src/theme";

const answerStyles: Record<StaffAnswer, { label: string; backgroundColor: string; color: string }> = {
  contains: { label: "Contains", backgroundColor: "#FBE7E4", color: "#9D231E" },
  shared_utensils: { label: "Cross-contact", backgroundColor: "#FFF1D3", color: "#805300" },
  does_not_contain: { label: "Not an ingredient", backgroundColor: "#E4F3EC", color: "#075E49" },
  unknown: { label: "Unknown", backgroundColor: "#FFFFFF", color: colors.ink },
};

export default function ResultScreen() {
  const { id, dish_id: dishId, demo } = useLocalSearchParams<{ id?: string; dish_id?: string; demo?: string }>();
  const source = demo === "okinawa" ? okinawaMenuDemo() : id ? getMenuAnalysis(id) : null;
  const menu = source && source.menu_id === id ? applyLocalConfirmations(source) : null;
  const dish = menu?.dishes.find((item) => item.dish_id === dishId);
  const selectedIds = demo === "okinawa" ? [3, 23] : getSelectedAllergenIds();
  const answers = selectedIds.map((allergenId) => dish?.allergens.find((item) => item.allergen_id === allergenId));
  const complete = Boolean(dish && selectedIds.length > 0 && answers.every((item) => item?.current_answer));
  const contains = complete ? answers.filter((item) => item?.current_answer?.answer === "contains") : [];
  const crossContact = complete && answers.some((item) => item?.current_answer?.answer === "shared_utensils");
  const unknown = complete && answers.some((item) => item?.current_answer?.answer === "unknown");
  const recheck = complete && answers.some((item) => item?.notices.ai_staff_mismatch || item?.notices.recheck_current_answer);
  const result = contains.length
    ? { title: "Not safe for you", description: `Staff reported ${contains.map((item) => item?.display_name).join(" and ")} as ${contains.length === 1 ? "an ingredient" : "ingredients"}.`, background: "#FBE7E4", color: "#9D231E" }
    : crossContact
      ? { title: "Cross-contact reported", description: "Staff reported shared cooking utensils. Ingredients are not confirmed.", background: "#FFF1D3", color: "#805300" }
      : unknown
        ? { title: "Please ask staff again", description: "Staff could not confirm every selected allergen.", background: "#F3F6F4", color: colors.ink }
        : { title: "Staff answers recorded", description: "Staff reported these are not ingredients. Cross-contact has not been confirmed.", background: "#E4F3EC", color: "#075E49" };

  const backToMenu = () => router.replace({
    pathname: "/menu",
    params: demo === "okinawa" ? { demo: "okinawa" } : id ? { id } : {},
  });

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.canvas}>
      <View style={styles.phone}>
        <View style={styles.content}>
          {complete && dish ? (
            <>
              <Text style={styles.dishName}>{dish.display_name || dish.name}{dish.display_name && dish.display_name !== dish.name ? ` ${dish.name}` : ""}</Text>

              <View style={[styles.resultBanner, { backgroundColor: result.background }]}>
                <Text style={[styles.resultTitle, { color: result.color }]}>{result.title}</Text>
                <Text style={[styles.resultDescription, { color: result.color }]}>{result.description}</Text>
              </View>

              <View style={styles.tableHeader}>
                <Text style={styles.columnHeading}>Your allergen</Text>
                <Text style={styles.columnHeading}>Staff answer</Text>
              </View>
              <View style={styles.answerTable}>
                {answers.map((item, index) => {
                  const answer = item!.current_answer!.answer;
                  const appearance = answerStyles[answer];
                  return (
                    <View key={item!.allergen_id} style={[styles.answerRow, index > 0 && styles.rowDivider]}>
                      <Text style={styles.allergenName}>{item!.display_name}</Text>
                      <Text style={[styles.answerBadge, { backgroundColor: appearance.backgroundColor, color: appearance.color }]}>{appearance.label}</Text>
                    </View>
                  );
                })}
              </View>
              {recheck ? <Text style={styles.recheck}>The menu estimate and staff answer differ. Please check with staff again.</Text> : null}
            </>
          ) : (
            <Text accessibilityRole="alert" style={styles.unavailable}>This confirmation is not available in this tab.</Text>
          )}
        </View>

        <Pressable accessibilityRole="button" onPress={backToMenu} style={styles.backButton}>
          <Text style={styles.backText}>Back to menu</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  canvas: { flexGrow: 1, alignItems: "center" },
  phone: { width: "100%", maxWidth: 440, flexGrow: 1, paddingHorizontal: 20, paddingTop: 24, paddingBottom: 26 },
  content: { flexGrow: 1, justifyContent: "center", paddingVertical: 24 },
  dishName: { color: colors.ink, fontSize: 25, lineHeight: 32, fontWeight: "800", marginBottom: 26 },
  resultBanner: { borderRadius: 18, padding: 20, marginBottom: 32 },
  resultTitle: { fontSize: 21, lineHeight: 27, fontWeight: "800" },
  resultDescription: { fontSize: 14, lineHeight: 21, marginTop: 6 },
  tableHeader: { flexDirection: "row", paddingHorizontal: 14, marginBottom: 9 },
  columnHeading: { flex: 1, color: colors.muted, fontSize: 13 },
  answerTable: { borderWidth: 1.5, borderColor: colors.line, borderRadius: 18, overflow: "hidden" },
  answerRow: { flexDirection: "row", minHeight: 62, alignItems: "center", paddingHorizontal: 14, gap: 8 },
  rowDivider: { borderTopWidth: 1, borderTopColor: colors.line },
  allergenName: { color: colors.ink, fontSize: 17, fontWeight: "700", flex: 1 },
  answerBadge: { fontSize: 13, fontWeight: "700", borderRadius: 14, overflow: "hidden", paddingHorizontal: 10, paddingVertical: 5, textAlign: "center", flexShrink: 1 },
  recheck: { color: "#805300", fontSize: 13, lineHeight: 19, marginTop: 18 },
  unavailable: { color: colors.muted, fontSize: 15, textAlign: "center" },
  backButton: { minHeight: 54, borderRadius: 28, backgroundColor: colors.green, alignItems: "center", justifyContent: "center" },
  backText: { color: colors.white, fontSize: 16, fontWeight: "800" },
});
