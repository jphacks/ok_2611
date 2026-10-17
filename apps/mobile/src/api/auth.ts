export type AuthResponse = {
  account: {
    id: string;
    email: string;
    nickname: string;
    publish_consent: boolean;
  };
  access_token: string;
  token_type: "bearer";
  expires_at: string;
};

export type RegisterRequest = {
  email: string;
  nickname: string;
  password: string;
  publish_consent: boolean;
};

const configuredBaseUrl = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();

export const isApiConfigured =
  Boolean(configuredBaseUrl) && !configuredBaseUrl?.includes("YOUR_API_BASE_URL");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function postAuth(path: string, body: object): Promise<AuthResponse> {
  if (!isApiConfigured || !configuredBaseUrl) {
    throw new ApiError(0, "api_not_configured", "The API URL is not configured.");
  }

  let response: Response;
  try {
    response = await fetch(`${configuredBaseUrl.replace(/\/$/, "")}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not connect. Please try again.");
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (payload as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "request_failed",
      error?.message ?? "Something went wrong. Please try again.",
    );
  }
  const data = payload as AuthResponse | null;
  if (!data?.access_token || !data.account?.id) {
    throw new ApiError(0, "invalid_response", "The server response was incomplete.");
  }
  return data;
}

export function registerAccount(body: RegisterRequest): Promise<AuthResponse> {
  return postAuth("/auth/register", body);
}

export function loginAccount(body: { email: string; password: string }): Promise<AuthResponse> {
  return postAuth("/auth/login", body);
}

export function saveAccountToken(token: string): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem("meelyze.account_token", token);
  }
}
