import { router } from "expo-router";
import { StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { BrandLogo } from "../src/components/BrandLogo";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { colors } from "../src/theme";

export default function WelcomeScreen() {
  const { width } = useWindowDimensions();
  const logoAreaSize = Math.min(320, width - 48);
  const logoSize = Math.min(240, logoAreaSize);

  return (
    <Page>
      <View style={[styles.logoArea, { minHeight: logoAreaSize + 32 }]}>
        <BrandLogo width={logoSize} />
        <View style={styles.details}>
          <Text style={styles.copy}>
            Explore Japanese menus and ask restaurant staff about ingredients on one phone.
          </Text>
        </View>
      </View>
      <View style={styles.bottom}>
        <PrimaryButton label="Create account" onPress={() => router.push("/onboarding")} />
        <View style={styles.gap} />
        <PrimaryButton label="Log in" secondary onPress={() => router.push("/login")} />
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  logoArea: { flexGrow: 1, alignItems: "center", justifyContent: "center", paddingBottom: 32 },
  details: { width: "100%", marginTop: 16 },
  copy: { color: colors.muted, fontSize: 16, lineHeight: 24 },
  bottom: { marginTop: 56, flexShrink: 0 },
  gap: { height: 12 },
});
