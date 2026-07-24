import type { V2AuthoringConflictTarget } from "./v2AuthoringConflictEvents.ts";

export type { V2AuthoringConflictTarget } from "./v2AuthoringConflictEvents.ts";

export type V2AuthoringConflict = {
  target: V2AuthoringConflictTarget;
  operationPath: string;
  message: string;
  retry: () => Promise<void>;
  discard: () => Promise<void>;
};

type Listener = (conflict: V2AuthoringConflict | null) => void;

class V2AuthoringConflictStore {
  private conflict: V2AuthoringConflict | null = null;
  private readonly listeners = new Set<Listener>();

  current(): V2AuthoringConflict | null {
    return this.conflict;
  }

  raise(conflict: V2AuthoringConflict): void {
    this.conflict = conflict;
    this.notify();
  }

  async retry(): Promise<void> {
    const conflict = this.conflict;
    if (!conflict) return;
    await conflict.retry();
    if (this.conflict === conflict) this.clear();
  }

  async discard(): Promise<void> {
    const conflict = this.conflict;
    if (!conflict) return;
    await conflict.discard();
    if (this.conflict === conflict) this.clear();
  }

  clear(): void {
    this.conflict = null;
    this.notify();
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.conflict);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    for (const listener of this.listeners) listener(this.conflict);
  }
}

export const v2AuthoringConflictStore = new V2AuthoringConflictStore();
