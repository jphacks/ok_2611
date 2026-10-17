import { allergenOptions } from "../../src/content/preferences";

const validIds = new Set(allergenOptions.map((item) => item.id));

export async function POST(request: Request): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return invalidSelection();
  }

  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return invalidSelection();
  }
  const ids = (body as { allergen_ids?: unknown }).allergen_ids;
  if (!Array.isArray(ids) || ids.length < 1 || ids.length > validIds.size ||
      ids.some((id) => !Number.isInteger(id) || !validIds.has(id)) ||
      new Set(ids).size !== ids.length) {
    return invalidSelection();
  }

  return Response.json({ allergen_ids: ids }, { headers: { "Cache-Control": "no-store" } });
}

function invalidSelection(): Response {
  return Response.json(
    { error: { code: "invalid_allergen_ids", message: "Select at least one valid allergen." } },
    { status: 422, headers: { "Cache-Control": "no-store" } },
  );
}
