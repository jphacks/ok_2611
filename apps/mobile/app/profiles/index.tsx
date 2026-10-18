import { useEffect, useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { clearAccountSession, getAccountDetails, getAccountToken, getMe, isAccountAuthError, saveAccountDetails, type AccountDetails } from "../../src/api/auth";
import { allergenOptions } from "../../src/content/preferences";
import { endAccountSession } from "../../src/features/account/session";
import { getSelectedAllergenIds } from "../../src/features/profile/selection";
import { colors } from "../../src/theme";

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.field}>
      <View style={styles.fieldHeader}>
        <Text style={styles.label}>{label}</Text>
        <View style={styles.disabledEdit} accessibilityState={{ disabled: true }}>
          <Text style={styles.disabledEditText}>Edit</Text>
        </View>
      </View>
      <View style={styles.valueBox}><Text style={styles.valueText}>{value}</Text></View>
    </View>
  );
}

export default function ProfileScreen() {
  const { updated } = useLocalSearchParams<{ updated?: string }>();
  const [details, setDetails] = useState<AccountDetails | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [accountError, setAccountError] = useState("");
  const [loggedIn, setLoggedIn] = useState(true);

  useEffect(() => {
    let active = true;
    setDetails(getAccountDetails());
    setSelectedIds(getSelectedAllergenIds());
    setAccountError("");
    const token = getAccountToken();
    setLoggedIn(Boolean(token));
    if (token) {
      // ⑯ shows the nickname and email from GET /me; the tab copy is only a fallback while loading.
      getMe(token).then((account) => {
        if (!active) return;
        const next = { nickname: account.nickname, email: account.email, preview: false };
        saveAccountDetails(next);
        setDetails(next);
      }).catch((cause: unknown) => {
        if (!active) return;
        if (isAccountAuthError(cause)) {
          clearAccountSession();
          setLoggedIn(false);
          setDetails(null);
          setAccountError("Your login has expired. Please log in again.");
        } else {
          setAccountError("Could not load your account details.");
        }
      });
    }
    return () => { active = false; };
  }, [updated]);

  const selectedNames = allergenOptions
    .filter((item) => selectedIds.includes(item.id))
    .map((item) => item.display_name);

  function logOut() {
    endAccountSession();
    router.replace("/");
  }

  return (
    <View style={styles.screen}>
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.title}>Your profile</Text>
        <Text style={styles.subtitle}>Account details and allergens</Text>
        {details?.preview ? <Text style={styles.preview}>Preview details are stored in this tab. No account has been created.</Text> : null}
        {accountError ? <Text accessibilityRole="alert" style={styles.preview}>{accountError}</Text> : null}
        {!loggedIn ? (
          <Pressable accessibilityRole="button" onPress={() => router.push("/login")}><Text style={styles.login}>Log in</Text></Pressable>
        ) : null}

        <View style={styles.fields}>
          <ReadOnlyField label="Nickname" value={details?.nickname || "Not available in this tab"} />
          <ReadOnlyField label="Email address" value={details?.email || "Not available in this tab"} />
          <ReadOnlyField label="Password" value="Hidden for security" />
        </View>

        <View style={styles.allergenSection}>
          <View style={styles.allergenHeader}>
            <Text style={styles.allergenTitle}>Allergens</Text>
            <Pressable accessibilityRole="button" onPress={() => router.push("/profiles/edit")} style={styles.activeEdit}>
              <Text style={styles.activeEditText}>Edit ›</Text>
            </Pressable>
          </View>
          <Text style={styles.allergenList}>{selectedNames.length ? selectedNames.join(" · ") : "No allergens selected yet"}</Text>
        </View>

        {loggedIn ? (
          <Pressable accessibilityRole="button" onPress={logOut} style={styles.logoutButton}>
            <Text style={styles.logoutText}>Log out</Text>
          </Pressable>
        ) : null}

      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.white },
  body: { paddingTop: 28, paddingHorizontal: 20, paddingBottom: 20 },
  title: { color: colors.ink, fontSize: 28, fontWeight: "800" },
  subtitle: { color: colors.muted, fontSize: 14, marginTop: 4 },
  preview: { color: colors.muted, fontSize: 12, lineHeight: 18, marginTop: 13, backgroundColor: "#F3F6F4", borderRadius: 10, padding: 10 },
  login: { color: colors.green, fontSize: 14, fontWeight: "700", marginTop: 12 },
  fields: { marginTop: 20, gap: 12 },
  fieldHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 },
  label: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  disabledEdit: { minWidth: 82, borderRadius: 20, paddingVertical: 7, alignItems: "center", backgroundColor: "#D1D5D3" },
  disabledEditText: { color: "#69726D", fontSize: 13, fontWeight: "700" },
  valueBox: { minHeight: 48, paddingHorizontal: 13, justifyContent: "center", borderColor: "#D5DDD8", borderWidth: 1.5, borderRadius: 12, backgroundColor: "#F6F8F7" },
  valueText: { color: colors.muted, fontSize: 14 },
  field: {},
  allergenSection: { marginTop: 28 },
  allergenHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  allergenTitle: { color: colors.ink, fontSize: 16, fontWeight: "800" },
  activeEdit: { backgroundColor: colors.green, borderRadius: 22, minWidth: 92, paddingVertical: 10, alignItems: "center" },
  activeEditText: { color: colors.white, fontSize: 14, fontWeight: "700" },
  allergenList: { color: colors.ink, fontSize: 15, lineHeight: 23, marginTop: 10 },
  logoutButton: { marginTop: 40, minHeight: 52, borderRadius: 26, borderWidth: 1.5, borderColor: colors.green, alignItems: "center", justifyContent: "center" },
  logoutText: { color: colors.green, fontSize: 16, fontWeight: "700" },
});
