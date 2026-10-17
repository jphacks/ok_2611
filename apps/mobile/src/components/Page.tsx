import type { PropsWithChildren } from "react";
import { ScrollView, StyleSheet, Text } from "react-native";
import { colors } from "../theme";

type PageProps = PropsWithChildren<{ step?: string; title?: string; subtitle?: string }>;

export function Page({ children, step, title, subtitle }: PageProps) {
  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      {step ? <Text style={styles.step}>{step}</Text> : null}
      {title ? <Text style={styles.title}>{title}</Text> : null}
      {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      {children}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.white },
  content: {
    flexGrow: 1,
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 32,
  },
  step: { color: colors.muted, fontSize: 12, alignSelf: "flex-end", fontWeight: "600", marginBottom: 20 },
  title: { color: colors.ink, fontSize: 30, fontWeight: "800", letterSpacing: -1.1, lineHeight: 36 },
  subtitle: { color: colors.muted, fontSize: 14, lineHeight: 22, marginTop: 10, marginBottom: 29 },
});
