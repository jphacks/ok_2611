import type { MenuAllergen, MenuResult } from "../../api/menus";

export type BadgeTone = "danger" | "caution" | "unknown" | "reportedAbsent";
export type MenuBadge = { allergenId: number; name: string; label: string; tone: BadgeTone };
export type SummaryDish = {
  dishId: string;
  name: string;
  originalName: string;
  price: number | null;
  currency: string;
  badges: MenuBadge[];
  confirmedAt: string | null;
  needsRecheck: boolean;
};
export type DetailAllergen = {
  id: number;
  name: string;
  status: MenuAllergen["ai"]["status"];
  source: MenuAllergen["ai"]["source"];
  evidence: string;
  staffAnswer: MenuAllergen["current_answer"];
};
export type DishDetail = {
  dishId: string;
  name: string;
  originalName: string;
  price: number | null;
  currency: string;
  description: string;
  likelyIngredients: string[];
  allergens: DetailAllergen[];
};
export type MenuSummary = {
  menuId: string;
  confirmed: SummaryDish[];
  estimates: SummaryDish[];
  details: Record<string, DishDetail>;
};

const answerLabels: Record<NonNullable<MenuAllergen["current_answer"]>["answer"], { text: string; tone: BadgeTone }> = {
  contains: { text: "Contains", tone: "danger" },
  shared_utensils: { text: "Shares utensils; ingredients unconfirmed", tone: "caution" },
  does_not_contain: { text: "Not an ingredient; cross-contact unconfirmed", tone: "reportedAbsent" },
  unknown: { text: "Unknown — ask again", tone: "unknown" },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isMenuResult(value: unknown): value is MenuResult {
  if (!isRecord(value) || typeof value.menu_id !== "string" || !Array.isArray(value.dishes) ||
      value.dishes.length < 1 || value.dishes.length > 20) return false;
  return value.dishes.every((dish: unknown) => isRecord(dish) &&
    typeof dish.dish_id === "string" && typeof dish.name === "string" &&
    typeof dish.display_name === "string" &&
    typeof dish.description === "string" &&
    (dish.price === null || (typeof dish.price === "number" && Number.isFinite(dish.price))) &&
    typeof dish.currency === "string" && Array.isArray(dish.allergens) &&
    dish.allergens.length <= 29 && dish.allergens.every((item: unknown) =>
      isRecord(item) && Number.isInteger(item.allergen_id) && typeof item.display_name === "string" &&
      isRecord(item.ai) && ["explicit_present", "possible", "unknown"].includes(String(item.ai.status)) &&
      (item.current_answer === null || (isRecord(item.current_answer) &&
        Object.hasOwn(answerLabels, String(item.current_answer.answer)) &&
        typeof item.current_answer.confirmed_at === "string")) &&
      isRecord(item.notices)));
}

function latestDate(items: MenuAllergen[]): string | null {
  const dates = items.flatMap((item) => item.current_answer ? [item.current_answer.confirmed_at] : []);
  return dates.length ? dates.sort().at(-1) ?? null : null;
}

function aiBadge(item: MenuAllergen | undefined, fallbackName: string, allergenId: number): MenuBadge {
  const name = item?.display_name || fallbackName;
  if (item?.ai.status === "explicit_present") return { allergenId, name, label: `Listed on menu: ${name}`, tone: "danger" };
  if (item?.ai.status === "possible") return { allergenId, name, label: `May contain: ${name} (AI estimate)`, tone: "caution" };
  return { allergenId, name, label: `${name}: Unknown — ask staff`, tone: "unknown" };
}

function staffBadge(item: MenuAllergen | undefined, fallbackName: string, allergenId: number): MenuBadge {
  const name = item?.display_name || fallbackName;
  if (!item?.current_answer) return { allergenId, name, label: `${name}: Not answered`, tone: "unknown" };
  const answer = answerLabels[item.current_answer.answer];
  return { allergenId, name, label: `${name}: ${answer.text}`, tone: answer.tone };
}

export function buildMenuSummary(menu: MenuResult, selectedIds: number[], names: Record<number, string>): MenuSummary {
  const confirmed: SummaryDish[] = [];
  const estimates: SummaryDish[] = [];
  const details: Record<string, DishDetail> = {};
  for (const dish of menu.dishes) {
    const selected = selectedIds.map((id) => dish.allergens.find((item) => item.allergen_id === id));
    const hasCurrentAnswer = selected.some((item) => item?.current_answer != null);
    const relevant = selected.filter((item): item is MenuAllergen => item !== undefined);
    const summary: SummaryDish = {
      dishId: dish.dish_id,
      name: dish.display_name || dish.name,
      originalName: dish.display_name && dish.display_name !== dish.name ? dish.name : "",
      price: dish.price,
      currency: dish.currency,
      badges: selected.map((item, index) => hasCurrentAnswer
        ? staffBadge(item, names[selectedIds[index]] || `Allergen ${selectedIds[index]}`, selectedIds[index])
        : aiBadge(item, names[selectedIds[index]] || `Allergen ${selectedIds[index]}`, selectedIds[index])),
      confirmedAt: hasCurrentAnswer ? latestDate(relevant) : null,
      needsRecheck: relevant.some((item) => item.notices.ai_staff_mismatch ||
        item.notices.recheck_current_answer || item.notices.history_conflict ||
        item.notices.history_shared_utensils),
    };
    (hasCurrentAnswer ? confirmed : estimates).push(summary);
    details[dish.dish_id] = {
      dishId: dish.dish_id,
      name: summary.name,
      originalName: summary.originalName,
      price: dish.price,
      currency: dish.currency,
      description: dish.description,
      // API 4/5 do not return ingredient chips. Leave this slot empty until a detail API exists.
      likelyIngredients: [],
      allergens: selectedIds.map((id, index) => ({
        id,
        name: selected[index]?.display_name || names[id] || `Allergen ${id}`,
        status: selected[index]?.ai.status || "unknown",
        source: selected[index]?.ai.source || "unavailable",
        evidence: selected[index]?.ai.evidence || "",
        staffAnswer: selected[index]?.current_answer || null,
      })),
    };
  }
  return { menuId: menu.menu_id, confirmed, estimates, details };
}
