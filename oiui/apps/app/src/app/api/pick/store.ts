/**
 * Simple in-memory session store for QR pick flow.
 * Shared across API route handlers via module-level state.
 */

export type PickSession = {
  status: "waiting" | "scanned" | "picked";
  prompt?: string;
};

const sessions = new Map<string, PickSession>();

// Auto-expire sessions after 10 minutes
const EXPIRY_MS = 10 * 60 * 1000;
const timers = new Map<string, ReturnType<typeof setTimeout>>();

export function getSession(sessionId: string): PickSession | undefined {
  return sessions.get(sessionId);
}

export function setSession(sessionId: string, data: PickSession) {
  sessions.set(sessionId, data);

  // Reset expiry timer
  const existing = timers.get(sessionId);
  if (existing) clearTimeout(existing);
  timers.set(
    sessionId,
    setTimeout(() => {
      sessions.delete(sessionId);
      timers.delete(sessionId);
    }, EXPIRY_MS),
  );
}
