import { router, useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { Page } from "../../src/components/Page";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { colors } from "../../src/theme";

export default function ProfileSetupScreen() {
  const { created } = useLocalSearchParams<{ created?: string }>();
  return (
    <Page title="What can't you eat?" subtitle="Next, choose the allergens and dietary preferences you want to check.">
      {created === "1" ? <Text style={styles.success}>Account created.</Text> : null}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Your preferences</Text>
        <Text style={styles.copy}>Allergen and dietary preference selection will appear here.</Text>
      </View>
      <View style={styles.bottom}>
        <PrimaryButton label="Back to start" secondary onPress={() => router.replace("/")} />
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  success: { color: colors.greenDark, backgroundColor: colors.greenPale, padding: 12, borderRadius: 10, marginBottom: 18, fontWeight: "700" },
  card: { borderWidth: 1, borderColor: colors.line, backgroundColor: colors.white, borderRadius: 16, padding: 20 },
  cardTitle: { color: colors.ink, fontSize: 16, fontWeight: "700", marginBottom: 8 },
  copy: { color: colors.muted, fontSize: 13, lineHeight: 20 },
  bottom: { marginTop: 36 },
});
