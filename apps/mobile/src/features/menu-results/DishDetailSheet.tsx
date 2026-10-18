import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import type { DishDetail } from "./summary";
import { IngredientIcon } from "../../components/IngredientIcon";
import { colors } from "../../theme";

type Props = {
  detail: DishDetail | null;
  onClose: () => void;
  onAskStaff: () => void;
};

const statuses = {
  explicit_present: { label: "Listed", background: "#FBE7E4", color: "#9D231E", border: "#FBE7E4" },
  possible: { label: "Possible", background: "#FFF1D3", color: "#805300", border: "#FFF1D3" },
  unknown: { label: "Unknown", background: "#FFFFFF", color: colors.ink, border: "#B8C8BF" },
} as const;

export function DishDetailSheet({ detail, onClose, onAskStaff }: Props) {
  const price = detail?.price == null ? "" : `${detail.currency === "JPY" ? "¥" : `${detail.currency} `}${detail.price}`;
  return (
    <Modal transparent animationType="slide" visible={detail !== null} onRequestClose={onClose}>
      <View style={styles.overlay}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Close dish details" onPress={onClose} />
        {detail ? (
          <View style={styles.sheet}>
            <View style={styles.handle} />
            <ScrollView contentContainerStyle={styles.content}>
              <View style={styles.titleRow}>
                <Text style={styles.title}>{detail.name}</Text>
                <Text style={styles.aiTag}>AI estimate</Text>
              </View>
              <Text style={styles.original}>{detail.originalName}{detail.originalName && price ? " · " : ""}{price}</Text>

              <Text style={styles.caption}>AI-generated description</Text>
              <Text style={styles.description}>{detail.description || "A description is not available yet. Please ask restaurant staff."}</Text>

              <Text style={styles.heading}>Likely ingredients</Text>
              {detail.likelyIngredients.length ? (
                <View style={styles.ingredientRow}>
                  {detail.likelyIngredients.map((item) => <Text key={item} style={styles.ingredient}>{item}</Text>)}
                </View>
              ) : <Text style={styles.placeholder}>Ingredient details are not available yet. Please ask staff.</Text>}

              <Text style={styles.heading}>Your allergens</Text>
              <View style={styles.allergenBox}>
                {detail.allergens.map((item, index) => {
                  const status = statuses[item.status];
                  return (
                    <View key={item.id} style={[styles.allergenRow, index > 0 && styles.allergenDivider]}>
                      <View style={styles.allergenCopy}>
                        <IngredientIcon allergenId={item.id} size={28} />
                        <Text style={styles.allergenName}>{item.name}</Text>
                      </View>
                      <Text style={[styles.status, { backgroundColor: status.background, color: status.color, borderColor: status.border }]}>{status.label}</Text>
                    </View>
                  );
                })}
              </View>
            </ScrollView>
            <View style={styles.actions}>
              <Pressable accessibilityRole="button" onPress={onClose} style={[styles.action, styles.close]}><Text style={styles.closeText}>Close</Text></Pressable>
              <Pressable accessibilityRole="button" onPress={onAskStaff} style={[styles.action, styles.ask]}><Text style={styles.askText}>Ask staff</Text></Pressable>
            </View>
          </View>
        ) : null}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, justifyContent: "flex-end", alignItems: "center", backgroundColor: "rgba(20,31,27,0.42)" },
  sheet: { width: "100%", maxWidth: 440, maxHeight: "85%", minHeight: "65%", backgroundColor: colors.white, borderTopLeftRadius: 26, borderTopRightRadius: 26, paddingHorizontal: 20, paddingTop: 10, paddingBottom: 20 },
  handle: { width: 38, height: 6, borderRadius: 3, backgroundColor: "#C7D7CE", alignSelf: "center", marginBottom: 15 },
  content: { paddingBottom: 18 },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { color: colors.ink, fontSize: 24, fontWeight: "800", flex: 1 },
  aiTag: { color: colors.muted, borderStyle: "dashed", borderColor: "#9FB4A8", borderWidth: 1, borderRadius: 7, paddingHorizontal: 7, paddingVertical: 4, fontSize: 12, fontWeight: "700" },
  original: { color: colors.muted, fontSize: 13, marginTop: 3 },
  caption: { color: colors.muted, fontSize: 11, fontWeight: "700", marginTop: 22, textTransform: "uppercase" },
  description: { color: colors.ink, fontSize: 14, lineHeight: 20, marginTop: 7 },
  heading: { color: colors.ink, fontSize: 15, fontWeight: "800", marginTop: 20, marginBottom: 9 },
  ingredientRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  ingredient: { backgroundColor: "#F2F5F3", color: colors.ink, borderRadius: 14, paddingHorizontal: 9, paddingVertical: 5, fontSize: 12 },
  placeholder: { color: colors.muted, backgroundColor: "#F5F7F6", borderRadius: 10, padding: 10, fontSize: 13, lineHeight: 18 },
  allergenBox: { borderColor: colors.line, borderWidth: 1.5, borderRadius: 14, overflow: "hidden" },
  allergenRow: { flexDirection: "row", alignItems: "center", gap: 10, padding: 10 },
  allergenDivider: { borderTopColor: colors.line, borderTopWidth: 1 },
  allergenCopy: { flex: 1, flexDirection: "row", alignItems: "center", gap: 8 },
  allergenName: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  status: { borderWidth: 1, borderRadius: 12, overflow: "hidden", paddingHorizontal: 7, paddingVertical: 4, fontSize: 11, fontWeight: "700" },
  actions: { flexDirection: "row", gap: 10, paddingTop: 12, borderTopColor: colors.line, borderTopWidth: 1 },
  action: { flex: 1, alignItems: "center", justifyContent: "center", minHeight: 52, borderRadius: 28 },
  close: { backgroundColor: colors.white, borderColor: colors.green, borderWidth: 1.5 },
  ask: { backgroundColor: colors.green },
  closeText: { color: colors.green, fontWeight: "700" },
  askText: { color: colors.white, fontWeight: "700" },
});
