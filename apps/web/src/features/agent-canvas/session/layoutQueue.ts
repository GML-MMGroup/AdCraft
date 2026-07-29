import type { CanvasLayoutPositionV2 } from "../../../types-v2.ts";

type LayoutFlush = (positions: CanvasLayoutPositionV2[]) => Promise<unknown>;
type Waiter = {
  resolve: () => void;
  reject: (error: unknown) => void;
};

const MAX_LAYOUT_BATCH = 200;

export class AgentCanvasLayoutQueue {
  private readonly pending = new Map<string, CanvasLayoutPositionV2>();
  private readonly waiters: Waiter[] = [];
  private running = false;

  constructor(private readonly flush: LayoutFlush) {}

  enqueue(positions: CanvasLayoutPositionV2[]): Promise<void> {
    positions.forEach((position) => {
      this.pending.set(position.node_id, position);
    });
    const promise = new Promise<void>((resolve, reject) => {
      this.waiters.push({ resolve, reject });
    });
    void this.drain();
    return promise;
  }

  private async drain(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      while (this.pending.size) {
        const positions = Array.from(this.pending.values());
        this.pending.clear();
        const waiters = this.waiters.splice(0);
        try {
          for (let index = 0; index < positions.length; index += MAX_LAYOUT_BATCH) {
            await this.flush(positions.slice(index, index + MAX_LAYOUT_BATCH));
          }
          waiters.forEach(({ resolve }) => resolve());
        } catch (error) {
          waiters.forEach(({ reject }) => reject(error));
        }
      }
    } finally {
      this.running = false;
      if (this.pending.size) void this.drain();
    }
  }
}
