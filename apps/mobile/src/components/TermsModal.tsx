import { Modal, ScrollView, StyleSheet, Text, View } from "react-native";
import { estimateNotice, safetyNotice } from "../content/terms";
import { colors } from "../theme";
import { PrimaryButton } from "./PrimaryButton";

type TermsModalProps = { visible: boolean; onClose: () => void };

export function TermsModal({ visible, onClose }: TermsModalProps) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.dialog}>
          <Text style={styles.title}>Terms of Use</Text>
          <Text style={styles.subtitle}>Please read this before creating an account or using menu estimates.</Text>
          <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
            <View style={styles.notice}>
              <Text style={styles.noticeTitle}>Safety comes first</Text>
              <Text style={styles.copy}>{safetyNotice}</Text>
            </View>
            <Section title="What Meelyze+ provides">{estimateNotice}</Section>
            <Section title="Restaurant staff answers">
              You can ask staff to answer on your phone. Their answers are entered through this app and are not independently verified by Meelyze+. Confirm anything important before ordering or eating.
            </Section>
            <Section title="Menu scans and sharing">
              Menu photos are sent to the app server for analysis and are kept private. By accepting these terms and creating an account, you agree that menus you scan and staff answers may be shared publicly when a restaurant is selected and staff also agree. Your account details and dietary preferences are not published. Staff answers may still help future estimates for the same restaurant, even when they are not shown publicly.
            </Section>
            <Section title="Future estimates">
              Staff answers may help estimate ingredients for later scans at the same restaurant, even when those answers are not shown publicly. Estimates remain a guide and require confirmation with staff.
            </Section>
          </ScrollView>
          <View style={styles.actions}>
            <PrimaryButton label="Close" onPress={onClose} />
          </View>
        </View>
      </View>
    </Modal>
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
  overlay: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "rgba(8, 35, 27, 0.55)", padding: 16 },
  dialog: { width: "100%", maxWidth: 480, maxHeight: "90%", backgroundColor: colors.white, borderRadius: 22, padding: 22 },
  title: { color: colors.ink, fontSize: 25, fontWeight: "800" },
  subtitle: { color: colors.muted, fontSize: 13, lineHeight: 20, marginTop: 7, marginBottom: 16 },
  scroll: { flexShrink: 1 },
  content: { paddingBottom: 4 },
  notice: { padding: 16, borderRadius: 14, backgroundColor: "#FFF3DF", marginBottom: 22 },
  noticeTitle: { color: colors.ink, fontSize: 16, fontWeight: "800", marginBottom: 7 },
  section: { marginBottom: 21 },
  sectionTitle: { color: colors.ink, fontSize: 15, fontWeight: "800", marginBottom: 6 },
  copy: { color: colors.muted, fontSize: 13, lineHeight: 21 },
  actions: { marginTop: 12 },
});
