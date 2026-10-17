import { allergenOptions } from "../../content/preferences";

const storageKey = "meelyze.selected_allergen_ids";
const validIds = new Set(allergenOptions.map((item) => item.id));

export function saveSelectedAllergenIds(ids: number[]): void {
  const unique = [...new Set(ids)].sort((a, b) => a - b);
  if (unique.length === 0 || unique.some((id) => !validIds.has(id))) {
    throw new Error("Select at least one valid allergen.");
  }
  window.sessionStorage.setItem(storageKey, JSON.stringify(unique));
}

export function getSelectedAllergenIds(): number[] {
  if (typeof window === "undefined") return [];
  try {
    const value: unknown = JSON.parse(window.sessionStorage.getItem(storageKey) ?? "null");
    if (!Array.isArray(value) || value.length === 0 || value.length > validIds.size ||
        value.some((id) => !Number.isInteger(id) || !validIds.has(id)) ||
        new Set(value).size !== value.length) return [];
    return value as number[];
  } catch {
    return [];
  }
}
