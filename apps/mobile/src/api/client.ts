export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

type RequestOptions = RequestInit & { networkMessage: string; failureMessage: string };

// Sends one request and maps the API's common error body ({"error": {"code", "message"}}) to ApiError.
// Never logs the request or response: they can hold tokens, emails, or allergen selections.
export async function requestJson(url: string, { networkMessage, failureMessage, ...init }: RequestOptions): Promise<{ status: number; payload: unknown }> {
  let response: Response;
  try {
    response = await fetch(url, { cache: "no-store", ...init });
  } catch {
    if (init.signal?.aborted) throw new ApiError(504, "timeout", "The request took too long. Please try again.");
    throw new ApiError(0, "network_error", networkMessage);
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = payload && typeof payload === "object" && "error" in payload
      ? (payload as { error?: { code?: string; message?: string } }).error : undefined;
    throw new ApiError(response.status, error?.code ?? "request_failed", error?.message ?? failureMessage);
  }
  return { status: response.status, payload };
}
