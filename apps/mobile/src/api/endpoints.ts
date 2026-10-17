// FastAPI base URL including /api/v1. EXPO_PUBLIC_API_BASE_URL can point a local build at another API;
// it is inlined at build time, so it must never hold a secret.
const defaultApiBaseUrl = "https://meelyze-api.vercel.app/api/v1";
export const apiBaseUrl = (process.env.EXPO_PUBLIC_API_BASE_URL?.trim() || defaultApiBaseUrl).replace(/\/+$/, "");

export const apiEndpoints: Record<"register" | "login" | "me" | "myAllergens" | "saveAllergens" | "analyzeMenu" | "getMenu" | "getDishDetails" | "createConfirmation", string> = {
  register: `${apiBaseUrl}/auth/register`, // POST
  login: `${apiBaseUrl}/auth/login`, // POST
  me: `${apiBaseUrl}/me`, // GET
  myAllergens: `${apiBaseUrl}/me/allergens`, // GET
  saveAllergens: `${apiBaseUrl}/me/allergens`, // PUT
  analyzeMenu: `${apiBaseUrl}/menus/analyze`, // POST
  getMenu: `${apiBaseUrl}/menus`, // GET /menus/{menu_id}; the client appends the menu ID
  getDishDetails: "", // Reserved for a future dish detail API. Contract and path are not defined yet.
  createConfirmation: `${apiBaseUrl}/menus`, // POST /menus/{menu_id}/confirmations; the client appends the rest
};

export function isEndpointConfigured(endpoint: keyof typeof apiEndpoints): boolean {
  return apiEndpoints[endpoint].trim().length > 0;
}
