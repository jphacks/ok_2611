import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors } from "../../theme";

export function AllergenChoices({ title, options, selected, onToggle }: {
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
              <Text style={[styles.chipText, isSelected && styles.chipTextSelected]}>{isSelected ? "✓  " : ""}{option.display_name}</Text>
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
});
