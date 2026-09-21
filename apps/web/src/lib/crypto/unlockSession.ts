export type ActiveUnlock = {
  document_id: string;
  claim_id: string;
  key: string;
  expires_at: string;
};

// Deliberately module-memory only: never localStorage/sessionStorage/cookies.
// It survives client-side navigation but disappears on refresh/tab close.
const activeUnlocks = new Map<string, ActiveUnlock>();

export function rememberUnlock(unlock: ActiveUnlock): void {
  activeUnlocks.set(unlock.document_id, unlock);
}

export function forgetUnlock(documentId: string): void {
  activeUnlocks.delete(documentId);
}

export function getActiveUnlocks(now = Date.now()): ActiveUnlock[] {
  for (const [documentId, unlock] of activeUnlocks) {
    if (Date.parse(unlock.expires_at) <= now) activeUnlocks.delete(documentId);
  }
  return [...activeUnlocks.values()];
}
