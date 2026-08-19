import type { CanvasLayoutPositionV2 } from "../../../types-v2.ts";

type LayoutFlush = (positions: CanvasLayoutPositionV2[]) => Promise<unknown>;
type Waiter = {
  resolve: () => void;
  reject: (error: unknown) => void;
};
type PositionOperation = {
  kind: "positions";
  pending: Map<string, CanvasLayoutPositionV2>;
  waiters: Waiter[];
};
type ExclusiveOperation = {
  kind: "exclusive";
  task: () => Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
};
type LayoutOperation = PositionOperation | ExclusiveOperation;

const MAX_LAYOUT_BATCH = 200;

export class AgentCanvasLayoutQueue {
  private readonly operations: LayoutOperation[] = [];
  private running = false;

  constructor(private readonly flush: LayoutFlush) {}

  enqueue(positions: CanvasLayoutPositionV2[]): Promise<void> {
    const tail = this.operations[this.operations.length - 1];
    const operation = tail?.kind === "positions"
      ? tail
      : {
          kind: "positions" as const,
          pending: new Map<string, CanvasLayoutPositionV2>(),
          waiters: [],
        };
    if (operation !== tail) this.operations.push(operation);
    positions.forEach((position) => {
      operation.pending.set(position.node_id, position);
    });
    const promise = new Promise<void>((resolve, reject) => {
      operation.waiters.push({ resolve, reject });
    });
    void this.drain();
    return promise;
  }

  runExclusive<T>(task: () => Promise<T>): Promise<T> {
    const promise = new Promise<T>((resolve, reject) => {
      this.operations.push({
        kind: "exclusive",
        task,
        resolve: (value) => resolve(value as T),
        reject,
      });
    });
    void this.drain();
    return promise;
  }

  private async drain(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      while (this.operations.length) {
        const operation = this.operations.shift();
        if (!operation) continue;
        if (operation.kind === "exclusive") {
          try {
            operation.resolve(await operation.task());
          } catch (error) {
            operation.reject(error);
          }
          continue;
        }

        const positions = Array.from(operation.pending.values());
        try {
          for (let index = 0; index < positions.length; index += MAX_LAYOUT_BATCH) {
            await this.flush(positions.slice(index, index + MAX_LAYOUT_BATCH));
          }
          operation.waiters.forEach(({ resolve }) => resolve());
        } catch (error) {
          operation.waiters.forEach(({ reject }) => reject(error));
        }
      }
    } finally {
      this.running = false;
      if (this.operations.length) void this.drain();
    }
  }
}
