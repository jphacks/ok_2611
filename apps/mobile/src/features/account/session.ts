import { clearAccountSession, saveAccountDetails, saveAccountToken, type AuthResponse } from "../../api/auth";
import { clearMenuAnalyses } from "../capture/analysis";
import { clearConfirmationResults } from "../menu-results/confirmationResults";
import { clearLocalConfirmations } from "../menu-results/localConfirmations";
import { clearSelectedAllergenIds, saveSelectedAllergenIds } from "../profile/selection";

// Starts a new account session in this tab without mixing in the previous account's menus or allergens.
export function startAccountSession(auth: AuthResponse, allergenIds: number[]): void {
  endAccountSession();
  saveAccountToken(auth.access_token, auth.account.id, auth.expires_at);
  saveAccountDetails({ nickname: auth.account.nickname, email: auth.account.email, preview: false });
  // An empty saved list does not mean "no allergies"; ⑤ asks for a selection again.
  if (allergenIds.length > 0) saveSelectedAllergenIds(allergenIds);
}

// Removes account-owned data from this tab before returning to the welcome screen.
export function endAccountSession(): void {
  clearAccountSession();
  clearMenuAnalyses();
  clearConfirmationResults();
  clearLocalConfirmations();
  clearSelectedAllergenIds();
}
