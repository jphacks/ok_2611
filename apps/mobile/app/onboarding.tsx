import { useState } from "react";
import { router } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { TermsModal } from "../src/components/TermsModal";
import { estimateNotice, safetyNotice } from "../src/content/terms";
import { colors } from "../src/theme";

export default function OnboardingScreen() {
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [termsOpened, setTermsOpened] = useState(false);
  const [termsVisible, setTermsVisible] = useState(false);

  function openTerms() {
    setTermsOpened(true);
    setTermsVisible(true);
  }

  return (
    <Page step="1 / 2" title="Before you start" subtitle="Language: English">
      <TermsModal visible={termsVisible} onClose={() => setTermsVisible(false)} />
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Safety comes first</Text>
        <Text style={styles.copy}>{safetyNotice}</Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.cardTitle}>About the estimates</Text>
        <Text style={styles.copy}>{estimateNotice}</Text>
      </View>
      <Pressable accessibilityRole="link" onPress={openTerms}>
        <Text style={styles.termsLink}>Read the Terms of Use and safety notice</Text>
      </Pressable>
      <Pressable
        accessibilityRole="checkbox"
        accessibilityState={{ checked: termsAccepted, disabled: !termsOpened }}
        disabled={!termsOpened}
        onPress={() => setTermsAccepted((accepted) => !accepted)}
        style={[styles.termsChoice, !termsOpened && styles.termsChoiceDisabled]}
      >
        <View style={[styles.termsBox, termsAccepted && styles.termsBoxSelected]}>
          {termsAccepted ? <Text style={styles.checkmark}>✓</Text> : null}
        </View>
        <Text style={styles.termsCopy}>I have read and agree to the Terms of Use.</Text>
      </Pressable>
      <View style={styles.card}>
        <Text style={styles.cardTitle}>One phone, two sides</Text>
        <Text style={styles.copy}>You read results in English. Restaurant staff can answer questions in Japanese on your phone.</Text>
      </View>
      <View style={styles.bottom}>
        <PrimaryButton
          label="Get started"
          disabled={!termsAccepted}
          onPress={() => router.push("/register?termsAccepted=1")}
        />
        <Pressable onPress={() => router.replace("/")}><Text style={styles.back}>Back</Text></Pressable>
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.greenPale, borderRadius: 16, padding: 19, marginBottom: 13 },
  cardTitle: { fontSize: 16, color: colors.ink, fontWeight: "700", marginBottom: 8 },
  copy: { color: colors.muted, fontSize: 14, lineHeight: 21 },
  termsLink: { color: colors.green, fontSize: 13, fontWeight: "700", marginBottom: 16, textDecorationLine: "underline" },
  termsChoice: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 44, marginBottom: 18 },
  termsChoiceDisabled: { opacity: 0.45 },
  termsBox: { width: 19, height: 19, borderRadius: 4, borderWidth: 1.5, borderColor: colors.muted, alignItems: "center", justifyContent: "center" },
  termsBoxSelected: { backgroundColor: colors.green, borderColor: colors.green },
  checkmark: { color: colors.white, fontSize: 14, fontWeight: "800", lineHeight: 16 },
  termsCopy: { flex: 1, color: colors.ink, fontSize: 13, lineHeight: 20 },
  bottom: { marginTop: 30 },
  back: { textAlign: "center", color: colors.muted, padding: 20, fontWeight: "600" },
});
