import type { PropsWithChildren } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { BrandLogo } from "./BrandLogo";
import { colors } from "../theme";

type PageProps = PropsWithChildren<{ step?: string; title?: string; subtitle?: string; showBrand?: boolean }>;

export function Page({ children, step, title, subtitle, showBrand = true }: PageProps) {
  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.canvas}>
      <View style={styles.phone}>
        {showBrand || step ? (
          <View style={styles.brandRow}>
            {showBrand ? <BrandLogo width={140} variant="header" /> : null}
            {step ? <Text style={styles.step}>{step}</Text> : null}
          </View>
        ) : null}
        {title ? <Text style={styles.title}>{title}</Text> : null}
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        {children}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.background },
  canvas: { minHeight: "100%", alignItems: "center", justifyContent: "center", padding: 20 },
  phone: {
    width: "100%",
    maxWidth: 440,
    minHeight: 620,
    backgroundColor: colors.white,
    borderRadius: 28,
    paddingHorizontal: 28,
    paddingTop: 30,
    paddingBottom: 32,
    borderWidth: 1,
    borderColor: colors.line,
    shadowColor: "#173C2D",
    shadowOpacity: 0.08,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 12 },
  },
  brandRow: { flexDirection: "row", alignItems: "center", marginBottom: 46 },
  step: { color: colors.muted, fontSize: 12, marginLeft: "auto", fontWeight: "600" },
  title: { color: colors.ink, fontSize: 30, fontWeight: "800", letterSpacing: -1.1, lineHeight: 36 },
  subtitle: { color: colors.muted, fontSize: 14, lineHeight: 22, marginTop: 10, marginBottom: 29 },
});
