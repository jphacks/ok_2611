import { router, useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { Page } from "../../src/components/Page";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { colors } from "../../src/theme";

export default function PlaceSelectScreen() {
  const { google_place_id: placeId, restaurant_name: restaurantName } = useLocalSearchParams<{
    google_place_id?: string; restaurant_name?: string;
  }>();

  return (
    <Page step="08 / Restaurant" title="Are you at this restaurant?" subtitle="Confirm a restaurant or skip to scan the menu.">
      {placeId ? (
        <View style={styles.candidate}>
          <Text style={styles.name}>{restaurantName || "Selected restaurant"}</Text>
        </View>
      ) : <Text style={styles.empty}>No restaurant is selected. You can still scan a menu.</Text>}
      <Text style={styles.hint}>If you skip, your scan will not be linked to a restaurant. Previous staff answers will not be used.</Text>
      <View style={styles.actions}>
        <View style={styles.action}><PrimaryButton label="Skip" secondary onPress={() => router.push("/capture")} /></View>
        {placeId ? <View style={styles.action}><PrimaryButton label="Confirm" onPress={() => router.push({ pathname: "/capture", params: { google_place_id: placeId, restaurant_name: restaurantName } })} /></View> : null}
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  candidate: { borderWidth: 2, borderColor: colors.green, borderRadius: 15, padding: 20 },
  name: { color: colors.ink, fontSize: 17, fontWeight: "700" },
  empty: { color: colors.ink, fontSize: 15, lineHeight: 22 },
  hint: { color: colors.muted, fontSize: 13, lineHeight: 20, marginTop: 18 },
  actions: { flexDirection: "row", gap: 12, marginTop: 44 },
  action: { flex: 1 },
});
