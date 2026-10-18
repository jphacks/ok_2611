import { createElement as h, type CSSProperties, type ReactNode } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { allergenAnswerKeys, type PublicAllergen, type PublicDish, type PublicMenus } from "../../api/publicMenus";
import type { NearbyPlace } from "../../api/places";
import { colors } from "../../theme";
import {
  aiSourceLabels, aiStatusLabels, allergenNotes, answerLabels, dishNames, formatDate, historyIndexLabel, priceLabel,
} from "./publicMenuDisplay";

export type PublicMenuState =
  | { status: "loading" }
  | { status: "ready"; data: PublicMenus }
  | { status: "error"; message: string }
  | { status: "needs_allergens" };

type Props = {
  place: NearbyPlace | null;
  attribution: string;
  state: PublicMenuState;
  retryDisabled: boolean;
  onClose: () => void;
  onRetry: () => void;
  onScan: () => void;
  onChooseAllergens: () => void;
};

const font = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const cell: CSSProperties = {
  borderTop: `1px solid ${colors.line}`, padding: "10px 10px", verticalAlign: "top", textAlign: "left",
  fontSize: 13, lineHeight: "19px", color: colors.ink, fontFamily: font, background: colors.white,
};
const headCell: CSSProperties = { ...cell, borderTop: 0, background: colors.background, color: colors.muted, fontSize: 12, fontWeight: 700 };
const columns = [
  { label: "Dish", width: 170 },
  { label: "Price", width: 86 },
  { label: "AI estimate", width: 190 },
  { label: "Public staff answers", width: 220 },
  { label: "Notes", width: 200 },
];
const statusColors = {
  explicit_present: { background: "#FBE7E4", color: "#9D231E" },
  possible: { background: "#FFF1D3", color: "#805300" },
  unknown: { background: colors.white, color: colors.ink },
} as const;

function muted(text: string, key?: string): ReactNode {
  return h("div", { key, style: { color: colors.muted, fontSize: 12, lineHeight: "17px", marginTop: 3 } }, text);
}

function AiCell({ item }: { item: PublicAllergen }) {
  const tone = statusColors[item.ai.status];
  return h("td", { style: cell },
    h("div", { style: { fontWeight: 700 } }, item.display_name),
    h("span", { style: {
      display: "inline-block", marginTop: 4, padding: "1px 7px", borderRadius: 6, fontSize: 12, fontWeight: 700,
      background: tone.background, color: tone.color, border: `1px solid ${item.ai.status === "unknown" ? "#B8C8BF" : tone.background}`,
    } }, aiStatusLabels[item.ai.status]),
    muted(aiSourceLabels[item.ai.source]),
    item.ai.evidence.trim() ? muted(`Evidence: “${item.ai.evidence.trim()}”`) : null,
  );
}

function AnswersCell({ item }: { item: PublicAllergen }) {
  const history = item.store_history;
  if (!history) {
    return h("td", { style: cell },
      h("div", { style: { fontWeight: 700 } }, item.display_name),
      muted("No public staff answers for this item."));
  }
  return h("td", { style: cell },
    h("div", { style: { fontWeight: 700 } }, item.display_name),
    h("ul", { style: { margin: "4px 0 0", padding: 0, listStyle: "none" } },
      allergenAnswerKeys.map((key) => {
        const date = formatDate(history.last_answered_at[key]);
        return h("li", { key }, `${answerLabels[key]}: ${history.answer_counts[key]}${date ? ` · last ${date}` : ""}`);
      })),
    muted(`Last confirmed ${formatDate(history.last_confirmed_at)}`),
    muted(historyIndexLabel(history.score)),
  );
}

function DishRows({ dish }: { dish: PublicDish }) {
  const { title, original } = dishNames(dish);
  const items = dish.allergens;
  const span = Math.max(items.length, 1);
  const dishCell = h("th", { scope: "rowgroup", rowSpan: span, style: { ...cell, position: "sticky", left: 0, zIndex: 1, fontWeight: 400 } },
    h("div", { style: { fontWeight: 800, fontSize: 14, overflowWrap: "anywhere" } }, title),
    original ? h("div", { style: { color: colors.muted, fontSize: 12, marginTop: 2, overflowWrap: "anywhere" } }, original) : null,
    dish.description.trim() ? h("details", { style: { marginTop: 6 } },
      h("summary", { style: { cursor: "pointer", color: colors.greenDark, fontSize: 12 } }, "AI-generated description"),
      h("div", { style: { fontSize: 12, lineHeight: "17px", marginTop: 4 } }, dish.description.trim())) : null,
  );
  const priceCell = h("td", { rowSpan: span, style: { ...cell, whiteSpace: "nowrap" } }, priceLabel(dish));
  if (items.length === 0) {
    return h("tbody", null, h("tr", null, dishCell, priceCell,
      h("td", { colSpan: 3, style: cell }, muted("No selected allergens to show for this dish. Ask staff."))));
  }
  return h("tbody", null, items.map((item, index) => h("tr", { key: item.allergen_id },
    index === 0 ? dishCell : null,
    index === 0 ? priceCell : null,
    h(AiCell, { item }),
    h(AnswersCell, { item }),
    h("td", { style: cell }, h("ul", { style: { margin: 0, paddingLeft: 16 } },
      allergenNotes(item).map((note) => h("li", { key: note }, note)))),
  )));
}

function MenuTable({ dishes, name }: { dishes: PublicDish[]; name: string }) {
  return h("div", { role: "region", "aria-label": "Shared menu table, scroll sideways for more columns", tabIndex: 0, style: {
    overflowX: "auto", maxWidth: "100%", border: `1px solid ${colors.line}`, borderRadius: 12, WebkitOverflowScrolling: "touch",
  } },
  h("table", { style: { borderCollapse: "separate", borderSpacing: 0, minWidth: columns.reduce((sum, c) => sum + c.width, 0) } },
    h("caption", { style: { position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" } }, `Shared menu analysis at ${name}`),
    h("colgroup", null, columns.map((c) => h("col", { key: c.label, style: { width: c.width } }))),
    h("thead", null, h("tr", null, columns.map((c, index) => h("th", { key: c.label, scope: "col", style: {
      ...headCell, ...(index === 0 ? { position: "sticky", left: 0, zIndex: 2 } : {}),
    } }, c.label)))),
    dishes.map((dish) => h(DishRows, { key: dish.name_key, dish })),
  ));
}

export function PublicMenuSheet({ place, attribution, state, retryDisabled, onClose, onRetry, onScan, onChooseAllergens }: Props) {
  const count = state.status === "ready" ? state.data.dishes.length : place?.public_menu_count ?? 0;
  const dialogLabel = { "aria-label": place ? `${place.name} shared menus` : "Shared menus" } as object;
  return (
    <Modal transparent animationType="slide" visible={place !== null} onRequestClose={onClose} {...dialogLabel}>
      <View style={styles.overlay}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityLabel="Close shared menus" onPress={onClose} />
        {place ? (
          <View style={styles.sheet}>
            <View style={styles.handle} />
            <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
              <Text accessibilityRole="header" aria-level={2} style={styles.title}>{place.name}</Text>
              {place.address ? <Text style={styles.address}>{place.address}</Text> : null}
              <Text style={styles.attribution}>{attribution}</Text>
              <Text style={styles.count}>{count === 1 ? "1 shared dish" : `${count} shared dishes`}</Text>
              <Text style={styles.notice}>
                Shared by other travellers. Dishes are matched by name at this restaurant. Staff answers were entered on
                travellers’ phones and are not verified. AI estimates are not staff answers. Always confirm with staff.
              </Text>
              {state.status === "loading" ? (
                <View style={styles.loading} accessibilityRole="progressbar" aria-label="Loading shared menus">
                  <ActivityIndicator color={colors.green} />
                  <Text style={styles.muted}>Loading shared menus…</Text>
                </View>
              ) : null}
              {state.status === "error" ? (
                <View style={styles.block}>
                  <Text accessibilityRole="alert" style={styles.error}>{state.message}</Text>
                  <Pressable accessibilityRole="button" disabled={retryDisabled} accessibilityState={{ disabled: retryDisabled }}
                    onPress={onRetry} style={[styles.inlineButton, retryDisabled && styles.disabled]}>
                    <Text style={styles.inlineButtonText}>Try again</Text>
                  </Pressable>
                </View>
              ) : null}
              {state.status === "needs_allergens" ? (
                <View style={styles.block}>
                  <Text style={styles.muted}>Select your allergens in Profile to see shared answers for them.</Text>
                  <Pressable accessibilityRole="button" onPress={onChooseAllergens} style={styles.inlineButton}>
                    <Text style={styles.inlineButtonText}>Choose allergens</Text>
                  </Pressable>
                </View>
              ) : null}
              {state.status === "ready" && state.data.dishes.length === 0 ? (
                <View style={styles.block}>
                  <Text style={styles.empty}>No shared menus yet.</Text>
                  <Text style={styles.muted}>Scan the menu here to check it with staff.</Text>
                </View>
              ) : null}
              {state.status === "ready" && state.data.dishes.length > 0 ? <MenuTable dishes={state.data.dishes} name={place.name} /> : null}
            </ScrollView>
            <View style={styles.actions}>
              <Pressable accessibilityRole="button" onPress={onClose} style={[styles.action, styles.close]}>
                <Text style={styles.closeText}>Close</Text>
              </Pressable>
              <Pressable accessibilityRole="button" onPress={onScan} style={[styles.action, styles.scan]}>
                <Text style={styles.scanText}>Scan the menu at this restaurant</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, justifyContent: "flex-end", alignItems: "center", backgroundColor: "rgba(20,31,27,0.42)" },
  sheet: {
    width: "100%", maxWidth: 440, maxHeight: "88%", minHeight: "55%", backgroundColor: colors.white,
    borderTopLeftRadius: 26, borderTopRightRadius: 26, paddingTop: 10,
    paddingBottom: "calc(16px + env(safe-area-inset-bottom, 0px))" as unknown as number,
  },
  handle: { width: 38, height: 6, borderRadius: 3, backgroundColor: "#C7D7CE", alignSelf: "center", marginBottom: 12 },
  scroll: { flexShrink: 1 },
  content: { paddingHorizontal: 20, paddingBottom: 16 },
  title: { color: colors.ink, fontSize: 22, fontWeight: "800", lineHeight: 28 },
  address: { color: colors.muted, fontSize: 13, lineHeight: 19, marginTop: 4 },
  attribution: { color: colors.muted, fontSize: 11, marginTop: 4 },
  count: { color: colors.greenDark, fontSize: 14, fontWeight: "700", marginTop: 12 },
  notice: { color: colors.ink, fontSize: 12, lineHeight: 18, backgroundColor: colors.background, borderRadius: 10, padding: 10, marginTop: 10, marginBottom: 14 },
  loading: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 12 },
  block: { gap: 10, paddingVertical: 6 },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 20 },
  empty: { color: colors.ink, fontSize: 16, fontWeight: "700" },
  error: { color: colors.error, fontSize: 14, lineHeight: 21 },
  inlineButton: { alignSelf: "flex-start", borderWidth: 1.5, borderColor: colors.green, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 9 },
  inlineButtonText: { color: colors.greenDark, fontSize: 14, fontWeight: "700" },
  disabled: { opacity: 0.45 },
  actions: { flexDirection: "row", gap: 10, paddingHorizontal: 20, paddingTop: 12, borderTopWidth: 1, borderTopColor: colors.line },
  action: { minHeight: 48, borderRadius: 14, alignItems: "center", justifyContent: "center", paddingHorizontal: 12 },
  close: { flex: 1, borderWidth: 1.5, borderColor: colors.line },
  closeText: { color: colors.ink, fontSize: 15, fontWeight: "700" },
  scan: { flex: 2.4, backgroundColor: colors.green },
  scanText: { color: colors.white, fontSize: 14, fontWeight: "800", textAlign: "center" },
});
