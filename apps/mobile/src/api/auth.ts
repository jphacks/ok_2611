import { ApiError, requestJson } from "./client";
import { apiEndpoints, isEndpointConfigured } from "./endpoints";

export { ApiError } from "./client";

export type Account = {
  id: string;
  email: string;
  nickname: string;
  publish_consent: boolean;
  publish_consent_recorded_at: string;
  publish_consent_version: string;
  created_at: string;
};

export type AuthResponse = {
  account: Account;
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

export type AccountDetails = { nickname: string; email: string; preview: boolean };
const accountDetailsKey = "meelyze.account_details";
const accountTokenKey = "meelyze.account_token";
const accountIdKey = "meelyze.account_id";
const accountExpiresKey = "meelyze.account_token_expires_at";

export function saveAccountDetails(details: AccountDetails): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(accountDetailsKey, JSON.stringify(details));
}

export function getAccountDetails(): AccountDetails | null {
  if (typeof window === "undefined") return null;
  try {
    const value: unknown = JSON.parse(window.sessionStorage.getItem(accountDetailsKey) || "null");
    if (!value || typeof value !== "object") return null;
    const details = value as Partial<AccountDetails>;
    return typeof details.nickname === "string" && typeof details.email === "string" &&
      typeof details.preview === "boolean" ? details as AccountDetails : null;
  } catch {
    return null;
  }
}

export const isRegisterApiConfigured = isEndpointConfigured("register");
export const isLoginApiConfigured = isEndpointConfigured("login");

async function postAuth(url: string, body: object): Promise<AuthResponse> {
  if (!url.trim()) {
    throw new ApiError(0, "api_not_configured", "The API URL is not configured.");
  }
  const { payload } = await requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    networkMessage: "Could not connect. Please try again.",
    failureMessage: "Something went wrong. Please try again.",
  });
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

export async function getMe(accountToken: string): Promise<Account> {
  const { payload } = await requestJson(apiEndpoints.me, {
    headers: { Authorization: `Bearer ${accountToken}` },
    networkMessage: "Could not load your account. Please try again.",
    failureMessage: "Could not load your account.",
  });
  const account = payload as Account | null;
  if (!account?.id || typeof account.nickname !== "string" || typeof account.email !== "string") {
    throw new ApiError(0, "invalid_response", "The server response was incomplete.");
  }
  return account;
}

// An account token was rejected (invalid or expired) when the API answers 401 to an account-token request.
export function isAccountAuthError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export function saveAccountToken(token: string, accountId?: string, expiresAt?: string): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(accountTokenKey, token);
    if (accountId) window.sessionStorage.setItem(accountIdKey, accountId);
    if (expiresAt) window.sessionStorage.setItem(accountExpiresKey, expiresAt);
  }
}

export function getAccountToken(): string | null {
  return typeof window === "undefined" ? null : window.sessionStorage.getItem(accountTokenKey);
}

export function getAccountId(): string | null {
  return typeof window === "undefined" ? null : window.sessionStorage.getItem(accountIdKey);
}

// True while this tab holds an account token that has not passed the expires_at returned at login.
// This only decides which screens to show; the API still verifies the token on every request.
export function hasActiveAccountSession(): boolean {
  if (typeof window === "undefined") return false;
  if (!getAccountToken()) return false;
  const expiresAt = Date.parse(window.sessionStorage.getItem(accountExpiresKey) ?? "");
  if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) {
    clearAccountSession();
    return false;
  }
  return true;
}

// Returns the tab to the logged-out state. Device-only data such as the allergen selection stays.
export function clearAccountSession(): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(accountTokenKey);
  window.sessionStorage.removeItem(accountIdKey);
  window.sessionStorage.removeItem(accountExpiresKey);
  window.sessionStorage.removeItem(accountDetailsKey);
}
