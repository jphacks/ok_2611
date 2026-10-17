import { allergenOptions } from "../src/content/preferences";
import { okinawaMenuDemo } from "../src/features/menu-results/demo";
import { isMenuResult } from "../src/features/menu-results/summary";

const validIds = new Set(allergenOptions.map((item) => item.id));
const validAnswers = new Set(["contains", "shared_utensils", "does_not_contain", "unknown"]);
const headers = { "Cache-Control": "no-store" };

function invalid(message = "すべての項目に回答してください。"): Response {
  return Response.json({ error: { code: "answers_invalid", message } }, { status: 422, headers });
}

export async function POST(request: Request): Promise<Response> {
  const raw = await request.text();
  if (raw.length > 1_000_000) return invalid("回答データが大きすぎます。");
  let body: unknown;
  try { body = JSON.parse(raw); } catch { return invalid(); }
  if (!body || typeof body !== "object" || Array.isArray(body)) return invalid();
  const payload = body as Record<string, unknown>;
  const demo = payload.demo === "okinawa";
  const menu = demo ? okinawaMenuDemo() : payload.menu;
  if (!isMenuResult(menu) || payload.menuId !== menu.menu_id || typeof payload.dishId !== "string") return invalid("料理を確認できませんでした。");
  const dish = menu.dishes.find((item) => item.dish_id === payload.dishId);
  if (!dish) return invalid("料理を確認できませんでした。");

  const selectedIds = payload.selectedAllergenIds;
  if (!Array.isArray(selectedIds) || selectedIds.length === 0 || selectedIds.length > 29 ||
      selectedIds.some((id) => !Number.isInteger(id) || !validIds.has(id) || !dish.allergens.some((item) => item.allergen_id === id)) ||
      new Set(selectedIds).size !== selectedIds.length ||
      (demo && (selectedIds.length !== 2 || !selectedIds.includes(3) || !selectedIds.includes(23)))) return invalid("確認対象の項目が正しくありません。");

  const answers = payload.answers;
  if (!Array.isArray(answers) || answers.length !== selectedIds.length) return invalid();
  const received = new Set<number>();
  for (const item of answers) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return invalid();
    const { allergen_id: id, answer } = item as Record<string, unknown>;
    if (!Number.isInteger(id) || !selectedIds.includes(id) || !validAnswers.has(answer as string) || received.has(id as number)) return invalid();
    received.add(id as number);
  }
  if (received.size !== selectedIds.length) return invalid();
  return Response.json({ valid: true }, { headers });
}
