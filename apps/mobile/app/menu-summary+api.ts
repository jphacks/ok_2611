import { allergenOptions } from "../src/content/preferences";
import { okinawaMenuDemo } from "../src/features/menu-results/demo";
import { buildMenuSummary, isMenuResult } from "../src/features/menu-results/summary";

const names = Object.fromEntries(allergenOptions.map((item) => [item.id, item.display_name]));
const validIds = new Set(allergenOptions.map((item) => item.id));
const headers = { "Cache-Control": "no-store" };

function error(status: number, message: string): Response {
  return Response.json({ error: message }, { status, headers });
}

export async function GET(request: Request): Promise<Response> {
  const mode = new URL(request.url).searchParams.get("demo");
  if (mode !== "okinawa" && mode !== "wheat-pork" && mode !== "wheat-pork-confirmed") return error(404, "Preview not found.");
  // Old preview URLs also resolve to the first analysis. No staff answers exist in this fixture.
  return Response.json({ summary: buildMenuSummary(okinawaMenuDemo(), [3, 23], names) }, { headers });
}

export async function POST(request: Request): Promise<Response> {
  const raw = await request.text();
  if (raw.length > 1_000_000) return error(413, "Menu result is too large.");
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return error(400, "Invalid JSON.");
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return error(422, "Invalid result.");
  const { menu, selectedAllergenIds } = payload as { menu?: unknown; selectedAllergenIds?: unknown };
  if (!isMenuResult(menu) || !Array.isArray(selectedAllergenIds) || selectedAllergenIds.length < 1 ||
      selectedAllergenIds.length > validIds.size ||
      selectedAllergenIds.some((id) => !Number.isInteger(id) || !validIds.has(id)) ||
      new Set(selectedAllergenIds).size !== selectedAllergenIds.length) return error(422, "Invalid menu or allergens.");
  return Response.json({ summary: buildMenuSummary(menu, selectedAllergenIds as number[], names) }, { headers });
}
