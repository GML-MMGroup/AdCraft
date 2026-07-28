type QueueTask = () => Promise<unknown>;

type QueueWaiter = {
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
};

type QueueEntry = {
  key: string;
  task: QueueTask;
  waiters: QueueWaiter[];
};

export class AgentCanvasAuthoringQueue {
  private readonly pending: QueueEntry[] = [];
  private running = false;
  private readonly onError?: (error: unknown, key: string) => void;

  constructor(options: { onError?: (error: unknown, key: string) => void } = {}) {
    this.onError = options.onError;
  }

  enqueue<Result>(
    key: string,
    task: () => Promise<Result>,
    options: { coalesce?: boolean } = {},
  ): Promise<Result> {
    const promise = new Promise<Result>((resolve, reject) => {
      const waiter = { resolve, reject };
      const existing = options.coalesce
        ? this.pending.find((entry) => entry.key === key)
        : undefined;
      if (existing) {
        existing.task = task;
        existing.waiters.push({
          resolve: (value) => resolve(value as Result),
          reject,
        });
        return;
      }
      this.pending.push({
        key,
        task,
        waiters: [{
          resolve: (value) => resolve(value as Result),
          reject,
        }],
      });
    });
    void this.drain();
    return promise;
  }

  get isBusy() {
    return this.running || this.pending.length > 0;
  }

  private async drain() {
    if (this.running) return;
    this.running = true;
    try {
      while (this.pending.length) {
        const entry = this.pending.shift();
        if (!entry) continue;
        try {
          const result = await entry.task();
          entry.waiters.forEach(({ resolve }) => resolve(result));
        } catch (error) {
          this.onError?.(error, entry.key);
          entry.waiters.forEach(({ reject }) => reject(error));
        }
      }
    } finally {
      this.running = false;
      if (this.pending.length) void this.drain();
    }
  }
}
