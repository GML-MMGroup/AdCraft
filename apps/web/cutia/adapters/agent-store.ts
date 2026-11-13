import { create } from "zustand";

// The AdCraft conversation owns AI generation; the embedded editor has no
// separate agent credentials, conversation store, or remote AI requests.
export const useAgentStore = create<{ messages: never[]; getMessages: () => never[]; initMessages: (messages: unknown[]) => void }>(() => ({
  messages: [], getMessages: () => [], initMessages: () => undefined,
}));
