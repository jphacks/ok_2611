import { router } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { BrandLogo } from "../src/components/BrandLogo";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { colors } from "../src/theme";

export default function WelcomeScreen() {
  return (
    <Page showBrand={false}>
      <View style={styles.space} />
      <View style={styles.logo}><BrandLogo width={160} /></View>
      <Text style={styles.title}>Understand the menu.{"\n"}Ask with confidence.</Text>
      <Text style={styles.copy}>
        Explore Japanese menus and ask restaurant staff about ingredients on one phone.
      </Text>
      <View style={styles.bottom}>
        <PrimaryButton label="Create account" onPress={() => router.push("/onboarding")} />
        <View style={styles.gap} />
        <PrimaryButton label="Log in" secondary onPress={() => router.push("/login")} />
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  space: { flex: 1, minHeight: 60 },
  logo: { width: 160, height: 160, alignSelf: "center", marginBottom: 16 },
  title: { color: colors.ink, fontSize: 32, lineHeight: 39, fontWeight: "800", letterSpacing: -1.2 },
  copy: { color: colors.muted, fontSize: 15, lineHeight: 24, marginTop: 16 },
  bottom: { marginTop: 56 },
  gap: { height: 12 },
});
