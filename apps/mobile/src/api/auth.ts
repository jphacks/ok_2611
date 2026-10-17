import { apiEndpoints, isEndpointConfigured } from "./endpoints";

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

export const isRegisterApiConfigured = isEndpointConfigured("register");
export const isLoginApiConfigured = isEndpointConfigured("login");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function postAuth(url: string, body: object): Promise<AuthResponse> {
  if (!url.trim()) {
    throw new ApiError(0, "api_not_configured", "The API URL is not configured.");
  }

  let response: Response;
  try {
    response = await fetch(url, {
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
  return postAuth(apiEndpoints.register, body);
}

export function loginAccount(body: { email: string; password: string }): Promise<AuthResponse> {
  return postAuth(apiEndpoints.login, body);
}

export function saveAccountToken(token: string): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem("meelyze.account_token", token);
  }
}

export function getAccountToken(): string | null {
  return typeof window === "undefined" ? null : window.sessionStorage.getItem("meelyze.account_token");
}
