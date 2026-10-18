import type { AiSource, AllergenAiStatus, AllergenAnswerKey, PublicAllergen, PublicDish } from "../../api/publicMenus";

// Wording for ⑦. AI estimates and shared staff answers stay in separate columns and are never merged into one
// verdict. Missing information is shown as missing, never as "does not contain".
export const aiStatusLabels: Record<AllergenAiStatus, string> = {
  explicit_present: "Listed on menu",
  possible: "Possible",
  unknown: "Unknown",
};

export const aiSourceLabels: Record<AiSource, string> = {
  menu_text: "From the menu text",
  recipe_inference: "AI guess from typical recipes",
  dish_name_inference: "AI guess from the dish name",
  unavailable: "No information found",
};

export const answerLabels: Record<AllergenAnswerKey, string> = {
  contains: "Contains",
  shared_utensils: "Shared utensils",
  does_not_contain: "Does not contain",
  unknown: "Unknown",
};

export function dishNames(dish: PublicDish): { title: string; original: string } {
  const translated = dish.display_name.trim();
  const original = dish.name.trim();
  const title = translated || original || "Unnamed dish";
  return { title, original: original && original !== title ? original : "" };
}

// null means the menu did not list a price; 0 is shown as a real price.
export function priceLabel(dish: PublicDish): string {
  if (dish.price === null) return "Not listed";
  if (dish.currency === "JPY") return `¥${dish.price.toLocaleString("en-US")}`;
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: dish.currency }).format(dish.price);
  } catch {
    return `${dish.currency} ${dish.price}`.trim();
  }
}

export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isFinite(date.getTime())
    ? date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })
    : "";
}

// The history index is S=α/(α+β) over "contains" vs "does not contain" answers, weighted by age.
// It is a tendency among those answers, not a probability that the dish is safe or contains the allergen.
export function historyIndexLabel(score: number | null): string {
  return score === null
    ? "No Contains / Does not contain answers yet"
    : `History index ${score.toFixed(2)} (share of “Contains”, newer answers weigh more)`;
}

export function allergenNotes(item: PublicAllergen): string[] {
  const notes: string[] = [];
  const history = item.store_history;
  if (item.notices.history_conflict) notes.push("Staff answers disagree: some said Contains, some Does not contain.");
  if (item.notices.history_shared_utensils) notes.push("Shared utensils were reported.");
  if (history && history.answer_counts.unknown > 0) notes.push("Some staff answered Unknown.");
  if (!history && item.ai.status === "unknown") notes.push("No information. This does not mean it is absent.");
  else if (!history) notes.push("No shared staff answer yet.");
  notes.push("Ask staff to confirm before ordering.");
  return notes;
}
