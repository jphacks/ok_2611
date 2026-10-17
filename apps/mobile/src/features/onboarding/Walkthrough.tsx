import { useRef, useState } from "react";
import { Image, Pressable, StyleSheet, Text, useWindowDimensions, View } from "react-native";
import { BrandLogo } from "../../components/BrandLogo";
import { Page } from "../../components/Page";
import { PrimaryButton } from "../../components/PrimaryButton";
import { colors } from "../../theme";
import { walkthroughContent, type WalkthroughLanguage } from "./content";

const images = [
  require("../../../assets/onboarding_1.webp"),
  require("../../../assets/onboarding_2.webp"),
  require("../../../assets/onboarding_3.webp"),
  require("../../../assets/onboarding_4.webp"),
];

export function Walkthrough({ language, onFinish }: { language: WalkthroughLanguage; onFinish: () => void }) {
  const copy = walkthroughContent[language];
  const steps = copy.steps;
  const [index, setIndex] = useState(0);
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  const { width, height } = useWindowDimensions();
  const imageSize = Math.min(340, width - 48, Math.max(180, height - 440));
  const step = steps[index];
  const lastStep = index === steps.length - 1;

  return (
    <Page>
      <View style={styles.header}>
        <BrandLogo width={140} variant="header" />
        <Pressable accessibilityRole="button" accessibilityLabel={copy.skipLabel} onPress={onFinish} style={styles.skip}>
          <Text style={styles.skipText}>{copy.skip}</Text>
        </Pressable>
      </View>
      <View
        accessibilityRole="progressbar"
        accessibilityLabel={copy.progressLabel}
        aria-valuemin={1}
        aria-valuemax={steps.length}
        aria-valuenow={index + 1}
        aria-valuetext={copy.progressValue(index + 1, steps.length)}
        style={styles.progress}
      >
        {steps.map((item, position) => (
          <View key={item.title} style={[styles.segment, position <= index && styles.segmentActive]} />
        ))}
      </View>
      <View
        style={styles.story}
        onTouchStart={(event) => {
          const touch = event.nativeEvent.touches[0];
          touchStart.current = touch ? { x: touch.pageX, y: touch.pageY } : null;
        }}
        onTouchCancel={() => { touchStart.current = null; }}
        onTouchEnd={(event) => {
          const start = touchStart.current;
          const touch = event.nativeEvent.changedTouches[0];
          touchStart.current = null;
          if (!start || !touch) return;
          const dx = touch.pageX - start.x;
          const dy = touch.pageY - start.y;
          if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
          setIndex((current) => Math.max(0, Math.min(steps.length - 1, current + (dx < 0 ? 1 : -1))));
        }}
      >
        <View accessibilityLiveRegion="polite" style={styles.heading}>
          <Text accessibilityRole="header" style={styles.title}>{step.title}</Text>
        </View>
        <View style={styles.illustration}>
          <Image source={images[index]} accessibilityLabel={step.imageLabel} resizeMode="contain" style={{ width: imageSize, height: imageSize }} />
        </View>
        <Text style={styles.description}>{step.description}</Text>
      </View>
      <View style={styles.footer}>
        <View style={styles.actions}>
          {index > 0 ? (
            <PrimaryButton label={copy.back} secondary onPress={() => setIndex((current) => Math.max(0, current - 1))} />
          ) : null}
          <View style={styles.next}>
            <PrimaryButton
              label={lastStep ? copy.finish : copy.next}
              onPress={lastStep ? onFinish : () => setIndex((current) => Math.min(steps.length - 1, current + 1))}
            />
          </View>
        </View>
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 22 },
  skip: { minHeight: 44, minWidth: 44, alignItems: "center", justifyContent: "center" },
  skipText: { color: colors.muted, fontSize: 14, fontWeight: "600" },
  progress: { flexDirection: "row", gap: 6, marginBottom: 22 },
  segment: { flex: 1, height: 4, borderRadius: 2, backgroundColor: colors.line },
  segmentActive: { backgroundColor: colors.green },
  story: { flexGrow: 1 },
  heading: { minHeight: 72 },
  title: { color: colors.ink, fontSize: 30, fontWeight: "800", letterSpacing: -1.1, lineHeight: 36 },
  illustration: { flexGrow: 1, alignItems: "center", justifyContent: "center", paddingVertical: 16 },
  description: { color: colors.muted, fontSize: 15, lineHeight: 23, minHeight: 92 },
  footer: { marginTop: 24 },
  actions: { flexDirection: "row", gap: 12 },
  next: { flex: 1 },
});
