import { useEffect, useState } from "react";
import { router } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { isAllergenSaveConfigured, saveAllergens } from "../../src/api/allergens";
import { getAccountToken } from "../../src/api/auth";
import { allergenOptions } from "../../src/content/preferences";
import { AllergenChoices } from "../../src/features/profile/AllergenChoices";
import { getSelectedAllergenIds, saveSelectedAllergenIds } from "../../src/features/profile/selection";
import { colors } from "../../src/theme";

export default function ProfileEditScreen() {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { setSelected(new Set(getSelectedAllergenIds())); }, []);

  const toggle = (id: number) => {
    if (checking) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setError("");
  };

  const save = async () => {
    if (checking) return;
    setChecking(true);
    setError("");
    try {
      const ids = [...selected].sort((a, b) => a - b);
      const response = await fetch("/profiles/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allergen_ids: ids }),
      });
      if (response.status === 422) {
        setError("Select at least one allergen.");
        return;
      }
      const result: unknown = await response.json().catch(() => null);
      const returned = result && typeof result === "object" && "allergen_ids" in result ? result.allergen_ids : null;
      if (!response.ok || JSON.stringify(returned) !== JSON.stringify(ids)) {
        setError("Could not verify your selection. Please try again.");
        return;
      }
      if (isAllergenSaveConfigured) {
        const token = getAccountToken();
        if (!token) {
          setError("Log in before saving your profile.");
          return;
        }
        const saved = await saveAllergens(ids, token);
        if (JSON.stringify(saved.allergen_ids) !== JSON.stringify(ids)) {
          setError("The saved selection did not match. Please try again.");
          return;
        }
      }
      saveSelectedAllergenIds(ids);
      router.replace("/profiles?updated=1");
    } catch {
      setError("Could not save your allergens. Please try again.");
    } finally {
      setChecking(false);
    }
  };

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.title}>Edit allergens</Text>
        <Text style={styles.subtitle}>Select the ingredients you need to avoid.</Text>
        <AllergenChoices
          title="Allergens (Mandatory labeling, 9 items)"
          options={allergenOptions.filter((item) => item.category === "required")}
          selected={selected}
          onToggle={toggle}
        />
        <AllergenChoices
          title="Allergens (Recommended labeling, 20 items)"
          options={allergenOptions.filter((item) => item.category === "recommended")}
          selected={selected}
          onToggle={toggle}
        />
      </ScrollView>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <Pressable accessibilityRole="button" disabled={checking} onPress={() => void save()} style={[styles.save, checking && styles.disabled]}>
        <Text style={styles.saveText}>{checking ? "Checking…" : "Save changes"}</Text>
      </Pressable>
      <View style={styles.tabBar}>
        <Pressable accessibilityRole="button" onPress={() => router.push("/map")}><Text style={styles.tab}>⌖{"\n"}Map</Text></Pressable>
        <Pressable accessibilityRole="button" onPress={() => router.push("/capture")}><Text style={styles.tab}>▣{"\n"}Scan</Text></Pressable>
        <Pressable accessibilityRole="button" onPress={() => router.replace("/profiles")}><Text style={[styles.tab, styles.activeTab]}>●{"\n"}Profile</Text></Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  body: { paddingTop: 24, paddingHorizontal: 20, paddingBottom: 24 },
  title: { color: colors.ink, fontSize: 27, fontWeight: "800" },
  subtitle: { color: colors.muted, fontSize: 14, lineHeight: 21, marginTop: 5 },
  error: { color: colors.error, fontSize: 13, marginBottom: 8, marginHorizontal: 20 },
  save: { backgroundColor: colors.green, borderRadius: 28, minHeight: 54, alignItems: "center", justifyContent: "center", marginHorizontal: 20, marginBottom: 16 },
  disabled: { opacity: 0.5 },
  saveText: { color: colors.white, fontSize: 16, fontWeight: "800" },
  tabBar: { flexDirection: "row", justifyContent: "space-around", borderTopWidth: 1, borderColor: colors.line, paddingTop: 16, paddingBottom: 25 },
  tab: { color: colors.muted, fontSize: 12, textAlign: "center", lineHeight: 20 },
  activeTab: { color: colors.green, fontWeight: "700" },
});
