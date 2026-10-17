const prefix = "meelyze.local-staff-publish-consent.v1.";

function key(scope: string): string {
  return prefix + encodeURIComponent(scope);
}

export function getStaffPublishConsent(scope: string, preview: boolean): boolean | null {
  if (typeof window === "undefined") return null;
  const storage = preview ? window.sessionStorage : window.localStorage;
  const value = storage.getItem(key(scope));
  return value === "true" ? true : value === "false" ? false : null;
}

export function saveStaffPublishConsent(scope: string, consent: boolean, preview: boolean): void {
  if (typeof window === "undefined") throw new Error("Local preview is unavailable.");
  const storage = preview ? window.sessionStorage : window.localStorage;
  storage.setItem(key(scope), String(consent));
}
