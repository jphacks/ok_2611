import { useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { isAllergenSaveConfigured, saveAllergens } from "../../src/api/allergens";
import { getAccountToken } from "../../src/api/auth";
import { Page } from "../../src/components/Page";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { allergenOptions } from "../../src/content/preferences";
import { saveSelectedAllergenIds } from "../../src/features/profile/selection";
import { colors } from "../../src/theme";

export default function ProfileSetupScreen() {
  const { created } = useLocalSearchParams<{ created?: string }>();
  const [selectedAllergens, setSelectedAllergens] = useState<Set<number>>(new Set());
  const [selectionError, setSelectionError] = useState(false);
  const [checking, setChecking] = useState(false);
  const [saveError, setSaveError] = useState("");

  function toggleAllergen(id: number) {
    if (checking) return;
    const next = new Set(selectedAllergens);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedAllergens(next);
    setSelectionError(false);
    setSaveError("");
  }

  async function saveProfile() {
    if (checking) return;
    setChecking(true);
    setSelectionError(false);
    setSaveError("");
    try {
      const submittedIds = [...selectedAllergens].sort((a, b) => a - b);
      const response = await fetch("/profiles/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ allergen_ids: submittedIds }),
      });
      if (response.status === 422) {
        setSelectionError(true);
      } else {
        const result: unknown = await response.json().catch(() => null);
        const returnedIds = result && typeof result === "object" && "allergen_ids" in result
          ? result.allergen_ids : null;
        if (response.ok && JSON.stringify(returnedIds) === JSON.stringify(submittedIds)) {
          if (!isAllergenSaveConfigured) {
            saveSelectedAllergenIds(submittedIds);
            router.replace("/map");
          } else {
            const token = getAccountToken();
            if (!token) {
              setSaveError("Log in before saving your profile.");
            } else {
              const saved = await saveAllergens(submittedIds, token);
              if (JSON.stringify(saved.allergen_ids) !== JSON.stringify(submittedIds)) {
                setSaveError("The saved selection did not match. Please try again.");
              } else {
                saveSelectedAllergenIds(submittedIds);
                router.replace("/map");
              }
            }
          }
        } else {
          setSaveError("Could not verify your selection. Please try again.");
        }
      }
    } catch {
      setSaveError("Could not save your profile. Please try again.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <Page title="Allergens">
      {created === "1" ? <Text style={styles.success}>Account created.</Text> : null}

      <ChoiceSection
        title="Allergens (Mandatory labeling, 9 items)"
        options={allergenOptions.filter((item) => item.category === "required")}
        selected={selectedAllergens}
        onToggle={toggleAllergen}
      />
      <ChoiceSection
        title="Allergens (Recommended labeling, 20 items)"
        options={allergenOptions.filter((item) => item.category === "recommended")}
        selected={selectedAllergens}
        onToggle={toggleAllergen}
      />

      {selectionError ? (
        <Text accessibilityRole="alert" style={styles.error}>Select at least one allergen.</Text>
      ) : null}
      {saveError ? (
        <Text accessibilityRole="alert" style={styles.error}>{saveError}</Text>
      ) : null}
      <View style={styles.actions}>
        <PrimaryButton label={checking ? "Checking..." : "Save profile"} onPress={saveProfile} disabled={checking} />
      </View>
    </Page>
  );
}

function ChoiceSection({ title, options, selected, onToggle }: {
  title: string;
  options: Array<{ id: number; display_name: string }>;
  selected: Set<number>;
  onToggle: (id: number) => void;
}) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.chips}>
        {options.map((option) => {
          const isSelected = selected.has(option.id);
          return (
            <Pressable
              key={option.id}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: isSelected }}
              onPress={() => onToggle(option.id)}
              style={[styles.chip, isSelected && styles.chipSelected]}
            >
              <Text style={[styles.chipText, isSelected && styles.chipTextSelected]}>{option.display_name}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 24 },
  sectionTitle: { color: colors.ink, fontSize: 16, fontWeight: "800", marginBottom: 12 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { minHeight: 37, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 19, borderWidth: 1, borderColor: colors.line, backgroundColor: "#F6F8F6", justifyContent: "center" },
  chipSelected: { backgroundColor: colors.green, borderColor: colors.green },
  chipText: { color: colors.ink, fontSize: 13, fontWeight: "600" },
  chipTextSelected: { color: colors.white },
  error: { color: "#B42318", fontSize: 13, marginTop: 18 },
  success: { color: colors.greenDark, backgroundColor: colors.greenPale, padding: 12, borderRadius: 10, marginBottom: 14, fontWeight: "700" },
  actions: { marginTop: 26, gap: 11 },
});
