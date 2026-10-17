import type { MenuAnalysis } from "../../api/menus";

const prefix = "meelyze.analysis.";

export function saveMenuAnalysis(analysis: MenuAnalysis): void {
  window.sessionStorage.setItem(prefix + analysis.menu_id, JSON.stringify(analysis));
}

export function getMenuAnalysis(menuId: string): MenuAnalysis | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(prefix + menuId);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const analysis = parsed as MenuAnalysis;
    return analysis.menu_id === menuId && Array.isArray(analysis.dishes) ? analysis : null;
  } catch {
    return null;
  }
}
