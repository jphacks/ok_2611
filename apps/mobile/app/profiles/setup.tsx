import { useEffect, useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { isAllergenSaveConfigured, saveAllergens } from "../../src/api/allergens";
import { clearAccountSession, getAccountToken, isAccountAuthError } from "../../src/api/auth";
import { Page } from "../../src/components/Page";
import { PrimaryButton } from "../../src/components/PrimaryButton";
import { allergenOptions } from "../../src/content/preferences";
import { getSelectedAllergenIds, saveSelectedAllergenIds } from "../../src/features/profile/selection";
import { AllergenChoices } from "../../src/features/profile/AllergenChoices";
import { colors } from "../../src/theme";

export default function ProfileSetupScreen() {
  const { created } = useLocalSearchParams<{ created?: string }>();
  const [selectedAllergens, setSelectedAllergens] = useState<Set<number>>(new Set());
  const [selectionError, setSelectionError] = useState(false);
  const [checking, setChecking] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [needsLogin, setNeedsLogin] = useState(false);

  // After ④ the account's saved allergens are already in this tab; start from them.
  useEffect(() => { setSelectedAllergens(new Set(getSelectedAllergenIds())); }, []);

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
              setNeedsLogin(true);
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
    } catch (cause) {
      if (isAccountAuthError(cause)) {
        clearAccountSession();
        setNeedsLogin(true);
        setSaveError("Your login has expired. Please log in again.");
      } else {
        setSaveError("Could not save your profile. Please try again.");
      }
    } finally {
      setChecking(false);
    }
  }

  return (
    <Page title="Allergens">
      {created === "1" ? <Text style={styles.success}>Account created.</Text> : null}

      <AllergenChoices
        title="Allergens (Mandatory labeling, 9 items)"
        options={allergenOptions.filter((item) => item.category === "required")}
        selected={selectedAllergens}
        onToggle={toggleAllergen}
      />
      <AllergenChoices
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
        {needsLogin ? <PrimaryButton label="Log in" secondary onPress={() => router.push("/login")} /> : null}
        <PrimaryButton label="Back" secondary onPress={() => router.back()} disabled={checking} />
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  error: { color: "#B42318", fontSize: 13, marginTop: 18 },
  success: { color: colors.greenDark, backgroundColor: colors.greenPale, padding: 12, borderRadius: 10, marginBottom: 14, fontWeight: "700" },
  actions: { marginTop: 26, gap: 11 },
});
