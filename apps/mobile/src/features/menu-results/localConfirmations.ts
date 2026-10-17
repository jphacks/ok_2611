import type { MenuAllergen, MenuResult } from "../../api/menus";

export type StaffAnswer = NonNullable<MenuAllergen["current_answer"]>["answer"];

type Confirmation = {
  confirmedAt: string;
  publishConsent: boolean;
  answers: Record<string, StaffAnswer>;
};

const prefix = "meelyze.local-staff-confirmations.";
const allowed = new Set<StaffAnswer>(["contains", "shared_utensils", "does_not_contain", "unknown"]);

function read(menuId: string): Record<string, Confirmation> {
  if (typeof window === "undefined") return {};
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(prefix + menuId) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, Confirmation> : {};
  } catch {
    return {};
  }
}

export function saveLocalConfirmation(
  menu: MenuResult,
  dishId: string,
  answers: Record<number, StaffAnswer>,
  selectedIds: number[],
  publishConsent: boolean,
): void {
  if (typeof window === "undefined") throw new Error("Local preview is unavailable.");
  const dish = menu.dishes.find((item) => item.dish_id === dishId);
  if (!dish || selectedIds.length === 0 || selectedIds.length > 29 ||
      new Set(selectedIds).size !== selectedIds.length ||
      selectedIds.some((id) => !dish.allergens.some((item) => item.allergen_id === id) || !allowed.has(answers[id])) ||
      Object.keys(answers).length !== selectedIds.length) {
    throw new Error("すべての項目に回答してください。");
  }
  const saved = read(menu.menu_id);
  saved[dishId] = {
    confirmedAt: new Date().toISOString(),
    publishConsent,
    answers: Object.fromEntries(selectedIds.map((id) => [String(id), answers[id]])),
  };
  window.sessionStorage.setItem(prefix + menu.menu_id, JSON.stringify(saved));
}

export function applyLocalConfirmations(menu: MenuResult): MenuResult {
  const saved = read(menu.menu_id);
  return {
    ...menu,
    dishes: menu.dishes.map((dish) => {
      const confirmation = saved[dish.dish_id];
      if (!confirmation || !confirmation.answers || !Number.isFinite(Date.parse(confirmation.confirmedAt))) return dish;
      return {
        ...dish,
        allergens: dish.allergens.map((item) => {
          const answer = confirmation.answers[String(item.allergen_id)];
          if (!allowed.has(answer)) return item;
          return {
            ...item,
            current_answer: { answer, confirmed_at: confirmation.confirmedAt },
          };
        }),
      };
    }),
  };
}
