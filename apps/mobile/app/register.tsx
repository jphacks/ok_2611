import { useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { ApiError, isApiConfigured, registerAccount, saveAccountToken } from "../src/api/auth";
import { FormField } from "../src/components/FormField";
import { Page } from "../src/components/Page";
import { PrimaryButton } from "../src/components/PrimaryButton";
import { colors } from "../src/theme";

type FieldErrors = Partial<Record<"email" | "nickname" | "password" | "consent" | "terms", string>>;

export default function RegisterScreen() {
  const { termsAccepted: initialTermsAccepted } = useLocalSearchParams<{ termsAccepted?: string }>();
  const [email, setEmail] = useState("");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [consent, setConsent] = useState<boolean | null>(null);
  const [termsAccepted, setTermsAccepted] = useState(initialTermsAccepted === "1");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [serverError, setServerError] = useState("");
  const [previewDone, setPreviewDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    const nextErrors: FieldErrors = {};
    const cleanEmail = email.trim().toLowerCase();
    const cleanNickname = nickname.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) nextErrors.email = "Enter a valid email address.";
    if (cleanNickname.length < 1 || cleanNickname.length > 30) nextErrors.nickname = "Use 1–30 characters.";
    if (password.length < 8 || password.length > 128) nextErrors.password = "Use 8–128 characters.";
    else if (password.toLowerCase() === cleanEmail) nextErrors.password = "Choose a password different from your email.";
    if (consent === null) nextErrors.consent = "Choose one option to continue.";
    if (!termsAccepted) nextErrors.terms = "Read and accept the Terms of Use to continue.";
    setErrors(nextErrors);
    setServerError("");
    setPreviewDone(false);
    if (Object.keys(nextErrors).length) return;

    if (!isApiConfigured) {
      setPreviewDone(true);
      return;
    }

    setSubmitting(true);
    try {
      const result = await registerAccount({
        email: cleanEmail,
        nickname: cleanNickname,
        password,
        publish_consent: consent as boolean,
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

  return (
    <Page step="2 / 2" title="Create your account" subtitle="Enter your details to get started.">
      {!isApiConfigured ? (
        <View style={styles.preview}>
          <Text style={styles.previewText}>Preview mode · No account will be created until an API URL is configured.</Text>
        </View>
      ) : null}
      <FormField label="Nickname" placeholder="What should we call you?" value={nickname} onChangeText={setNickname} error={errors.nickname} maxLength={30} />
      <FormField label="Email address" placeholder="you@example.com" value={email} onChangeText={setEmail} error={errors.email} kind="email" />
      <FormField label="Password" placeholder="At least 8 characters" value={password} onChangeText={setPassword} error={errors.password} kind="password" maxLength={128} />

      <View style={styles.consentBlock}>
        <Text style={styles.consentTitle}>Sharing your menu scans</Text>
        <Text style={styles.consentCopy}>I agree to share menus I scan and staff answers when restaurant staff also agree.</Text>
        <View style={styles.choiceRow}>
          <ConsentChoice label="Agree" selected={consent === true} onPress={() => setConsent(true)} />
          <ConsentChoice label="Do not agree" selected={consent === false} onPress={() => setConsent(false)} />
        </View>
        {errors.consent ? <Text style={styles.error}>{errors.consent}</Text> : null}
        <Text style={styles.hint}>Your photos, account details, and personal preferences are never shared. Staff answers may still help future estimates for the same restaurant, even if you choose not to share them publicly.</Text>
      </View>

      <View style={styles.termsBlock}>
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked: termsAccepted }}
          onPress={() => setTermsAccepted((accepted) => !accepted)}
          style={styles.termsChoice}
        >
          <View style={[styles.termsBox, termsAccepted && styles.termsBoxSelected]}>
            {termsAccepted ? <Text style={styles.checkmark}>✓</Text> : null}
          </View>
          <Text style={styles.termsCopy}>I have read and agree to the Terms of Use.</Text>
        </Pressable>
        <Pressable accessibilityRole="link" onPress={() => router.push("/terms")}>
          <Text style={styles.termsLink}>Read the Terms of Use and safety notice</Text>
        </Pressable>
        {errors.terms ? <Text style={styles.error}>{errors.terms}</Text> : null}
      </View>

      {serverError ? <Text accessibilityRole="alert" style={styles.errorBox}>{serverError}</Text> : null}
      {previewDone ? <Text accessibilityRole="alert" style={styles.successBox}>Form checked. Connect the API to create a real account.</Text> : null}

      <View style={styles.actions}>
        <PrimaryButton label={submitting ? "Creating account…" : isApiConfigured ? "Create account" : "Check form"} onPress={submit} disabled={submitting || !termsAccepted} />
        <Pressable onPress={() => router.push("/login")}><Text style={styles.login}>Already have an account? <Text style={styles.loginLink}>Log in</Text></Text></Pressable>
        <Pressable onPress={() => router.back()}><Text style={styles.back}>Back</Text></Pressable>
      </View>
    </Page>
  );
}

function ConsentChoice({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      style={[styles.choice, selected && styles.choiceSelected]}
    >
      <View style={[styles.radio, selected && styles.radioSelected]}>{selected ? <View style={styles.radioDot} /> : null}</View>
      <Text style={[styles.choiceText, selected && styles.choiceTextSelected]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  preview: { padding: 11, borderRadius: 10, backgroundColor: "#F3F5E9", marginBottom: 20 },
  previewText: { color: "#536327", fontSize: 12, lineHeight: 18 },
  consentBlock: { marginTop: 4 },
  consentTitle: { color: colors.ink, fontSize: 14, fontWeight: "800", marginBottom: 7 },
  consentCopy: { color: colors.ink, fontSize: 13, lineHeight: 20, marginBottom: 12 },
  choiceRow: { flexDirection: "row", gap: 9 },
  choice: { flex: 1, minHeight: 45, borderWidth: 1.5, borderColor: colors.line, borderRadius: 12, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7, paddingHorizontal: 8 },
  choiceSelected: { borderColor: colors.green, backgroundColor: colors.greenPale },
  radio: { width: 16, height: 16, borderRadius: 8, borderWidth: 1.5, borderColor: "#8FA49A", alignItems: "center", justifyContent: "center" },
  radioSelected: { borderColor: colors.green },
  radioDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.green },
  choiceText: { color: colors.ink, fontSize: 12, fontWeight: "600" },
  choiceTextSelected: { color: colors.greenDark },
  hint: { color: colors.muted, fontSize: 11, lineHeight: 17, marginTop: 12 },
  termsBlock: { marginTop: 24, paddingTop: 20, borderTopWidth: 1, borderTopColor: colors.line },
  termsChoice: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 44 },
  termsBox: { width: 19, height: 19, borderRadius: 4, borderWidth: 1.5, borderColor: colors.muted, alignItems: "center", justifyContent: "center" },
  termsBoxSelected: { backgroundColor: colors.green, borderColor: colors.green },
  checkmark: { color: colors.white, fontSize: 14, fontWeight: "800", lineHeight: 16 },
  termsCopy: { flex: 1, color: colors.ink, fontSize: 13, lineHeight: 20 },
  termsLink: { color: colors.green, fontSize: 12, fontWeight: "700", marginTop: 5, marginLeft: 29, textDecorationLine: "underline" },
  error: { color: colors.error, fontSize: 12, marginTop: 5 },
  errorBox: { color: colors.error, backgroundColor: "#FDF0F0", borderRadius: 10, padding: 12, fontSize: 13, lineHeight: 19, marginTop: 16 },
  successBox: { color: colors.greenDark, backgroundColor: colors.greenPale, borderRadius: 10, padding: 12, fontSize: 13, lineHeight: 19, marginTop: 16 },
  actions: { marginTop: 26 },
  login: { textAlign: "center", color: colors.muted, fontSize: 13, marginTop: 19 },
  loginLink: { color: colors.green, fontWeight: "700" },
  back: { textAlign: "center", color: colors.muted, fontSize: 13, marginTop: 19, padding: 7 },
});
