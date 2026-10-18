import { useState } from "react";
import { router } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { getMyAllergens } from "../src/api/allergens";
import { ApiError, isLoginApiConfigured, loginAccount } from "../src/api/auth";
import { startAccountSession } from "../src/features/account/session";
import { FormField } from "../src/components/FormField";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { colors } from "../src/theme";

export default function LoginScreen() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setError("");
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    if (!isLoginApiConfigured) {
      setError("Preview mode: connect the API to log in.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await loginAccount({ email: email.trim().toLowerCase(), password });
      // ④ loads the saved allergens before ⑤ so the setup screen starts from the account's selection.
      let saved: { allergen_ids: number[] };
      try {
        saved = await getMyAllergens(result.access_token);
      } catch {
        setError("Could not load your saved allergens. Please try logging in again.");
        return;
      }
      startAccountSession(result, saved.allergen_ids);
      setPassword("");
      router.push("/profiles/setup");
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === "rate_limited") {
        setError("Too many attempts. Please wait and try again.");
      } else if (cause instanceof ApiError && cause.status === 401) {
        setPassword("");
        setError("The email address or password is incorrect.");
      } else {
        setError(cause instanceof Error ? cause.message : "Could not log in.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Page title="Log in to Meelyze+" subtitle="Enter your email and password.">
      <FormField label="Email address" placeholder="you@example.com" value={email} onChangeText={setEmail} kind="email" />
      <FormField label="Password" placeholder="Your password" value={password} onChangeText={setPassword} kind="password" passwordAutoComplete="current-password" />
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      <View style={styles.actions}>
        <PrimaryButton label={submitting ? "Logging in…" : "Log in"} onPress={submit} disabled={submitting} />
        <Pressable onPress={() => router.push("/onboarding")}><Text style={styles.link}>New here? <Text style={styles.green}>Create account</Text></Text></Pressable>
        <Pressable accessibilityRole="button" onPress={() => router.back()}><Text style={styles.back}>Back</Text></Pressable>
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  error: { color: colors.error, backgroundColor: "#FDF0F0", padding: 12, borderRadius: 10, fontSize: 13 },
  actions: { marginTop: 29 },
  link: { textAlign: "center", color: colors.muted, fontSize: 13, marginTop: 19 },
  green: { color: colors.green, fontWeight: "700" },
  back: { textAlign: "center", color: colors.muted, fontSize: 13, marginTop: 19, padding: 7 },
});
