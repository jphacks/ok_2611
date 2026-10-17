import type { ConfirmationResult, ConfirmedDish } from "../../api/menus";

// The saved confirmation as returned by the API, shared by ⑮ and ⑪′ in this tab only.
export type SavedDishConfirmation = Omit<ConfirmationResult, "results"> & { dish: ConfirmedDish };

const prefix = "meelyze.confirmation-results.";

function read(menuId: string): Record<string, SavedDishConfirmation> {
  if (typeof window === "undefined") return {};
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(prefix + menuId) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, SavedDishConfirmation> : {};
  } catch {
    return {};
  }
}

export function saveConfirmationResult(menuId: string, result: ConfirmationResult): void {
  const saved = read(menuId);
  const { results, ...session } = result;
  for (const dish of results) saved[dish.dish_id] = { ...session, dish };
  window.sessionStorage.setItem(prefix + menuId, JSON.stringify(saved));
}

export function getConfirmationResult(menuId: string, dishId: string): SavedDishConfirmation | null {
  const saved = read(menuId)[dishId];
  return saved && typeof saved.session_id === "string" && Array.isArray(saved.dish?.allergens) ? saved : null;
}

export function clearConfirmationResults(): void {
  if (typeof window === "undefined") return;
  for (const key of Object.keys(window.sessionStorage)) {
    if (key.startsWith(prefix)) window.sessionStorage.removeItem(key);
  }
}
