import { router, useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { getMenuAnalysis } from "../src/features/capture/analysis";
import { colors } from "../src/theme";

const statusText: Record<string, string> = {
  contains: "Likely contains",
  cross_contact: "Possible cross-contact",
  possible: "May contain (AI estimate)",
  unknown: "Unknown",
  not_contains: "Staff previously said does not contain",
};

export default function MenuScreen() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const analysis = id ? getMenuAnalysis(id) : null;
  if (!analysis) {
    return (
      <Page title="Analysis unavailable" subtitle="This tab has no saved result for that menu.">
        <PrimaryButton label="Scan a menu" onPress={() => router.replace("/places/select")} />
      </Page>
    );
  }

  return (
    <Page title="Analysis complete" subtitle={analysis.google_place_id ? "Restaurant selected" : "No restaurant selected. Previous staff answers are not used."}>
      <View style={styles.retake}>
        <PrimaryButton label="↻ Retake" secondary onPress={() => router.push({ pathname: "/capture", params: analysis.google_place_id ? { google_place_id: analysis.google_place_id } : {} })} />
      </View>
      <Text style={styles.warning}>Estimates only. Always confirm with restaurant staff.</Text>
      <Text style={styles.sectionTitle}>AI ESTIMATE · {analysis.dishes.length} DISHES</Text>
      {analysis.dishes.map((dish) => (
        <View key={dish.dish_id} style={styles.dish}>
          <View style={styles.dishTop}>
            <Text style={styles.name}>{dish.display_name || dish.name} {dish.display_name !== dish.name ? dish.name : ""}</Text>
            <Text style={styles.price}>{dish.price == null ? "" : `${dish.currency === "JPY" ? "¥" : dish.currency ?? ""}${dish.price}`}</Text>
          </View>
          {dish.allergens.length === 0 ? <Text style={styles.note}>Allergen information is unavailable. Ask staff.</Text> : (
            dish.allergens.map((item) => (
              <Text key={item.allergen_id} style={styles.prediction}>
                {item.display_name}: {statusText[item.prediction.status] ?? "Unknown"}
              </Text>
            ))
          )}
        </View>
      ))}
    </Page>
  );
}

const styles = StyleSheet.create({
  retake: { alignSelf: "flex-end", minWidth: 120, marginBottom: 20 },
  warning: { color: colors.ink, backgroundColor: "#FFF4DA", padding: 14, borderRadius: 12, lineHeight: 21 },
  sectionTitle: { color: colors.muted, fontSize: 14, fontWeight: "700", marginTop: 26, marginBottom: 12 },
  dish: { borderWidth: 1, borderColor: colors.line, borderRadius: 16, padding: 16, marginBottom: 12 },
  dishTop: { flexDirection: "row", justifyContent: "space-between", gap: 10 },
  name: { color: colors.ink, fontSize: 16, fontWeight: "700", flex: 1 },
  price: { color: colors.ink, fontSize: 15 },
  prediction: { color: colors.ink, backgroundColor: "#FFF4DA", marginTop: 8, padding: 8, borderRadius: 7 },
  note: { color: colors.muted, marginTop: 8 },
});
