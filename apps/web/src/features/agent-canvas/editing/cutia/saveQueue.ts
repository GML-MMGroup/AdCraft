import { snapshotKey, type CutiaSnapshot } from "./project.ts";

/** Serialize backend writes, coalescing drag updates without losing the latest edit. */
export class CutiaSaveQueue {
  private pending: CutiaSnapshot | null = null;
  private running: Promise<void> | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private savedKey: string;
  private failure: Error | null = null;
  constructor(initial: CutiaSnapshot, private save: (snapshot: CutiaSnapshot) => Promise<void>, private notify: (state: "saving" | "saved" | "error", error?: Error) => void) {
    this.savedKey = snapshotKey(initial);
  }
  get dirty() { return Boolean(this.pending || this.running); }
  enqueue(snapshot: CutiaSnapshot) {
    if (!this.running && snapshotKey(snapshot) === this.savedKey) { this.pending = null; return; }
    this.pending = snapshot;
    if (this.timer) clearTimeout(this.timer);
    this.notify("saving");
    if (!this.failure) this.timer = setTimeout(() => { void this.flush().catch(() => undefined); }, 300);
  }
  async flush(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.failure) throw this.failure;
    if (this.running) return this.running;
    this.running = (async () => {
      while (this.pending) {
        const snapshot = this.pending;
        this.pending = null;
        this.notify("saving");
        try { await this.save(snapshot); this.savedKey = snapshotKey(snapshot); }
        catch (cause) {
          this.pending ??= snapshot;
          this.failure = cause instanceof Error ? cause : new Error("Unable to save editing changes.");
          this.notify("error", this.failure);
          throw this.failure;
        }
      }
      this.notify("saved");
    })();
    try { await this.running; } finally { this.running = null; }
  }
  async retry() { this.failure = null; return this.flush(); }
  dispose() { if (this.timer) clearTimeout(this.timer); this.timer = null; }
}
