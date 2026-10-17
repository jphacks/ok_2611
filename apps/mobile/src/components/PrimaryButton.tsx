import { Pressable, StyleSheet, Text } from "react-native";
import { colors } from "../theme";

type Props = { label: string; onPress: () => void; disabled?: boolean; secondary?: boolean };

export function PrimaryButton({ label, onPress, disabled, secondary }: Props) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: Boolean(disabled) }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        secondary && styles.secondary,
        disabled && styles.disabled,
        pressed && !disabled && styles.pressed,
      ]}
    >
      <Text style={[styles.text, secondary && styles.secondaryText]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 52,
    paddingHorizontal: 20,
    borderRadius: 15,
    backgroundColor: colors.green,
    alignItems: "center",
    justifyContent: "center",
  },
  secondary: {
    backgroundColor: colors.white,
    borderColor: colors.green,
    borderWidth: 1.5,
  },
  disabled: { opacity: 0.5 },
  pressed: { opacity: 0.85 },
  text: { color: colors.white, fontSize: 15, fontWeight: "700" },
  secondaryText: { color: colors.green },
});
