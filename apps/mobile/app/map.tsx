import { router } from "expo-router";
import { Text, StyleSheet, View } from "react-native";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { colors } from "../src/theme";

export default function MapScreen() {
  return (
    <Page title="Map">
      <Text style={styles.message}>Under construction.</Text>
      <View style={styles.action}>
        <PrimaryButton label="Scan a menu" onPress={() => router.push("/places/select")} />
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  message: { color: colors.muted, fontSize: 16, marginTop: 18 },
  action: { marginTop: 32 },
});
