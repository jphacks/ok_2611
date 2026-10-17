const storageKey = "meelyze.walkthrough.seen";
let seenInMemory = false;

// Called after hydration. Recording the first display also covers leaving midway.
export function claimFirstVisit(): boolean {
  if (seenInMemory) return false;
  seenInMemory = true;

  try {
    if (window.localStorage.getItem(storageKey) === "1") return false;
    window.localStorage.setItem(storageKey, "1");
  } catch {
    // Storage may be blocked. Keep navigation usable and remember for this page.
  }

  return true;
}
