import { useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { colors } from "../theme";

type Props = {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  error?: string;
  kind?: "email" | "password" | "text";
  passwordAutoComplete?: "new-password" | "current-password";
  maxLength?: number;
};

export function FormField({ label, value, onChangeText, placeholder, error, kind = "text", passwordAutoComplete = "new-password", maxLength }: Props) {
  const [visible, setVisible] = useState(false);
  const password = kind === "password";
  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <View style={[styles.inputWrap, error && styles.inputError]}>
        <TextInput
          accessibilityLabel={label}
          autoCapitalize={kind === "email" ? "none" : "sentences"}
          autoComplete={kind === "email" ? "email" : password ? passwordAutoComplete : "nickname"}
          keyboardType={kind === "email" ? "email-address" : "default"}
          maxLength={maxLength}
          onChangeText={onChangeText}
          placeholder={placeholder}
          placeholderTextColor="#9BAAA2"
          secureTextEntry={password && !visible}
          style={styles.input}
          value={value}
        />
        {password ? (
          <Pressable accessibilityRole="button" accessibilityLabel={visible ? "Hide password" : "Show password"} onPress={() => setVisible((current) => !current)}>
            <Text style={styles.toggle}>{visible ? "Hide" : "Show"}</Text>
          </Pressable>
        ) : null}
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginBottom: 18 },
  label: { color: colors.ink, fontSize: 13, fontWeight: "700", marginBottom: 8 },
  inputWrap: {
    height: 51,
    borderWidth: 1.5,
    borderColor: colors.line,
    borderRadius: 13,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 14,
    backgroundColor: colors.white,
  },
  inputError: { borderColor: colors.error },
  input: { flex: 1, color: colors.ink, fontSize: 15, height: "100%" },
  toggle: { color: colors.green, fontWeight: "700", fontSize: 13, paddingLeft: 10 },
  error: { color: colors.error, fontSize: 12, marginTop: 5 },
});
