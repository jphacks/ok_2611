// External API URLs stay empty until the full user flow is ready to connect.
// Fill each complete URL (including /api/v1) here at the final integration step.
// An empty value must never trigger a network request.
export const apiEndpoints: Record<"register" | "login" | "saveAllergens" | "analyzeMenu" | "getMenu" | "getDishDetails" | "createConfirmation", string> = {
  register: "", // POST /api/v1/auth/register
  login: "", // POST /api/v1/auth/login
  saveAllergens: "", // PUT /api/v1/me/allergens
  analyzeMenu: "", // POST /api/v1/menus/analyze
  getMenu: "", // GET /api/v1/menus/{menu_id}; put the URL through /menus here
  getDishDetails: "", // Reserved for a future dish detail API. Contract and path are not defined yet.
  createConfirmation: "", // POST /api/v1/menus/{menu_id}/confirmations; put the URL through /menus here.
};

export function isEndpointConfigured(endpoint: keyof typeof apiEndpoints): boolean {
  return apiEndpoints[endpoint].trim().length > 0;
}
