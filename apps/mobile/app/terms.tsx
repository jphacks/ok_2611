import { router } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { estimateNotice, safetyNotice } from "../src/content/terms";
import { colors } from "../src/theme";

export default function TermsScreen() {
  return (
    <Page title="Terms of Use" subtitle="Please read this before creating an account or using menu estimates.">
      <View style={styles.notice}>
        <Text style={styles.noticeTitle}>Safety comes first</Text>
        <Text style={styles.copy}>{safetyNotice}</Text>
      </View>

      <Section title="What Meelyze+ provides">{estimateNotice}</Section>
      <Section title="Restaurant staff answers">
        You can ask staff to answer on your phone. Their answers are entered through this app and are not independently verified by Meelyze+. Confirm anything important before ordering or eating.
      </Section>
      <Section title="Menu scans and sharing">
        Menu photos are sent to the app server for analysis and are kept private. Your account details and dietary preferences are not published. A menu and staff answers can be shared publicly only when you choose to share during registration, a restaurant is selected, and staff also agree. Your sharing choice is separate from accepting these terms.
      </Section>
      <Section title="Future estimates">
        Staff answers may help estimate ingredients for later scans at the same restaurant, even when those answers are not shown publicly. Estimates remain a guide and require confirmation with staff.
      </Section>

      <View style={styles.actions}>
        <PrimaryButton label="Back" onPress={() => router.back()} />
      </View>
    </Page>
  );
}

function Section({ title, children }: { title: string; children: string }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <Text style={styles.copy}>{children}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  notice: { padding: 16, borderRadius: 14, backgroundColor: "#FFF3DF", marginBottom: 22 },
  noticeTitle: { color: colors.ink, fontSize: 16, fontWeight: "800", marginBottom: 7 },
  section: { marginBottom: 21 },
  sectionTitle: { color: colors.ink, fontSize: 15, fontWeight: "800", marginBottom: 6 },
  copy: { color: colors.muted, fontSize: 13, lineHeight: 21 },
  actions: { marginTop: 10 },
});
