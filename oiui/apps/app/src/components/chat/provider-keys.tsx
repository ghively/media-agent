"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

export type ProviderKeys = { openai: string; jev: string };
type ProviderKeysContextValue = {
  headers: Record<string, string> | undefined;
  hasKeys: boolean;
  /** Media-agent PoC: keys live in the agent's .env, so the browser asks for none. */
  serverKeys: boolean;
  session: number;
  save: (keys: ProviderKeys) => void;
  clear: () => void;
  newChat: () => void;
  draft: string;
  setDraft: (value: string) => void;
  keysOpen: boolean;
  setKeysOpen: (value: boolean) => void;
};
// NEXT_PUBLIC_SERVER_KEYS=true: the agent server holds the model keys (default for
// the media-agent PoC). Unset it to get Open Intelligent UI's bring-your-own-key dialog.
const SERVER_KEYS = process.env.NEXT_PUBLIC_SERVER_KEYS === "true";

const ProviderKeysContext = createContext<ProviderKeysContextValue | null>(null);

export function ProviderKeysProvider({ children }: { children: ReactNode }) {
  // Deliberately memory-only: never put credentials in browser storage or agent state.
  const [keys, setKeys] = useState<ProviderKeys | null>(null);
  const [session, setSession] = useState(0);
  const [draft, setDraft] = useState("");
  const [keysOpen, setKeysOpen] = useState(false);
  const newChat = () => { setDraft(""); setSession((value) => value + 1); };
  return (
    <ProviderKeysContext.Provider value={{
      headers: keys ? { "x-openai-api-key": keys.openai, "x-jev-api-key": keys.jev } : undefined,
      hasKeys: SERVER_KEYS || keys !== null,
      serverKeys: SERVER_KEYS,
      session,
      save: (value) => { setKeys(value); setKeysOpen(false); setSession((value) => value + 1); },
      clear: () => { setKeys(null); newChat(); },
      newChat, draft, setDraft, keysOpen, setKeysOpen,
    }}>
      {children}
    </ProviderKeysContext.Provider>
  );
}

export function useProviderKeys() {
  const value = useContext(ProviderKeysContext);
  if (!value) throw new Error("ProviderKeysProvider is required");
  return value;
}
