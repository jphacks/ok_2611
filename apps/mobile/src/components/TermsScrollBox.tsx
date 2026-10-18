import { useRef } from "react";
import { type NativeScrollEvent, type NativeSyntheticEvent, ScrollView, StyleSheet, Text, View } from "react-native";
import { estimateNotice, safetyNotice } from "../content/terms";
import { colors } from "../theme";

// Allow a few pixels of slack so sub-pixel rounding on the web still counts as the bottom.
const bottomThreshold = 8;

type TermsScrollBoxProps = { onReachEnd: () => void };

export function TermsScrollBox({ onReachEnd }: TermsScrollBoxProps) {
  const viewportHeight = useRef(0);
  const contentHeight = useRef(0);
  const reached = useRef(false);

  function check(offsetY: number) {
    if (reached.current || !viewportHeight.current || !contentHeight.current) return;
    if (offsetY + viewportHeight.current >= contentHeight.current - bottomThreshold) {
      reached.current = true;
      onReachEnd();
    }
  }

  function handleScroll(event: NativeSyntheticEvent<NativeScrollEvent>) {
    const { contentOffset, layoutMeasurement, contentSize } = event.nativeEvent;
    viewportHeight.current = layoutMeasurement.height;
    contentHeight.current = contentSize.height;
    check(contentOffset.y);
  }

  return (
    <View style={styles.frame}>
      <ScrollView
        accessibilityLabel="Terms of Use"
        style={styles.scroll}
        contentContainerStyle={styles.content}
        nestedScrollEnabled
        scrollEventThrottle={16}
        onScroll={handleScroll}
        onLayout={(event) => {
          viewportHeight.current = event.nativeEvent.layout.height;
          check(0);
        }}
        onContentSizeChange={(_, height) => {
          contentHeight.current = height;
          check(0);
        }}
      >
        <Text style={styles.title}>Terms of Use</Text>
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
    </View>
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
  frame: { borderWidth: 1, borderColor: colors.line, borderRadius: 16, backgroundColor: colors.white, overflow: "hidden" },
  scroll: { height: 280 },
  content: { padding: 18 },
  title: { color: colors.ink, fontSize: 18, fontWeight: "800", marginBottom: 14 },
  notice: { padding: 16, borderRadius: 14, backgroundColor: "#FFF3DF", marginBottom: 22 },
  noticeTitle: { color: colors.ink, fontSize: 16, fontWeight: "800", marginBottom: 7 },
  section: { marginBottom: 21 },
  sectionTitle: { color: colors.ink, fontSize: 15, fontWeight: "800", marginBottom: 6 },
  copy: { color: colors.muted, fontSize: 13, lineHeight: 21 },
});
