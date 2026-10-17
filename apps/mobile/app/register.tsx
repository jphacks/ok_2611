import { useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { ApiError, isRegisterApiConfigured, registerAccount, saveAccountToken } from "../src/api/auth";
import { FormField } from "../src/components/FormField";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { colors } from "../src/theme";

type FieldErrors = Partial<Record<"email" | "nickname" | "password", string>>;

export default function RegisterScreen() {
  const { termsAccepted: initialTermsAccepted } = useLocalSearchParams<{ termsAccepted?: string }>();
  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [serverError, setServerError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    const nextErrors: FieldErrors = {};
    const cleanEmail = email.trim().toLowerCase();
    const cleanNickname = nickname.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) nextErrors.email = "Enter a valid email address.";
    if (cleanNickname.length < 1 || cleanNickname.length > 30) nextErrors.nickname = "Use 1–30 characters.";
    if (password.length < 8 || password.length > 128) nextErrors.password = "Use 8–128 characters.";
    else if (password.toLowerCase() === cleanEmail) nextErrors.password = "Choose a password different from your email.";
    setErrors(nextErrors);
    setServerError("");
    if (Object.keys(nextErrors).length) return;

    if (!isRegisterApiConfigured) {
      router.push("/profiles/setup");
      return;
    }

    setSubmitting(true);
    try {
      const result = await registerAccount({
        email: cleanEmail,
        nickname: cleanNickname,
        password,
        publish_consent: true,
      });
      saveAccountToken(result.access_token);
      router.replace("/profiles/setup?created=1");
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "email_already_registered") {
          setServerError("This email address is already registered. Log in instead.");
        } else if (error.code === "rate_limited") {
          setServerError("Too many attempts. Please wait and try again.");
        } else if (error.code === "validation_error") {
          setServerError("Please check your details and try again.");
        } else {
          setServerError(error.message);
        }
      } else {
        setServerError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (initialTermsAccepted !== "1") {
    return (
      <Page title="Before creating an account" subtitle="Please review and agree to the Terms of Use on the previous screen first.">
        <PrimaryButton label="Review Terms of Use" onPress={() => router.replace("/onboarding")} />
      </Page>
    );
  }

  return (
    <Page step="2 / 2" title="Create your account" subtitle="Enter your details to get started.">
      {!isRegisterApiConfigured ? (
        <View style={styles.preview}>
          <Text style={styles.previewText}>Preview mode · No account will be created until an API URL is configured.</Text>
        </View>
      ) : null}
      <FormField label="Nickname" placeholder="What should we call you?" value={nickname} onChangeText={setNickname} error={errors.nickname} maxLength={30} />
      <FormField label="Email address" placeholder="you@example.com" value={email} onChangeText={setEmail} error={errors.email} kind="email" />
      <FormField label="Password" placeholder="At least 8 characters" value={password} onChangeText={setPassword} error={errors.password} kind="password" maxLength={128} />

      {serverError ? <Text accessibilityRole="alert" style={styles.errorBox}>{serverError}</Text> : null}

      <View style={styles.actions}>
        <PrimaryButton label={submitting ? "Creating account…" : isRegisterApiConfigured ? "Create account" : "Check form"} onPress={submit} disabled={submitting} />
        <Pressable onPress={() => router.push("/login")}><Text style={styles.login}>Already have an account? <Text style={styles.loginLink}>Log in</Text></Text></Pressable>
        <Pressable onPress={() => router.replace("/onboarding")}><Text style={styles.back}>Back</Text></Pressable>
      </View>
    </Page>
  );
}

const styles = StyleSheet.create({
  preview: { padding: 11, borderRadius: 10, backgroundColor: "#F3F5E9", marginBottom: 20 },
  previewText: { color: "#536327", fontSize: 12, lineHeight: 18 },
  errorBox: { color: colors.error, backgroundColor: "#FDF0F0", borderRadius: 10, padding: 12, fontSize: 13, lineHeight: 19, marginTop: 16 },
  actions: { marginTop: 26 },
  login: { textAlign: "center", color: colors.muted, fontSize: 13, marginTop: 19 },
  loginLink: { color: colors.green, fontWeight: "700" },
  back: { textAlign: "center", color: colors.muted, fontSize: 13, marginTop: 19, padding: 7 },
});
