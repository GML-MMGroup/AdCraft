type QueuedTask = {
  run: () => Promise<void>;
  priority: number;
  sequence: number;
};

function abortError() {
  const error = new Error("Request aborted");
  error.name = "AbortError";
  return error;
}

export function createRequestQueue(limit: number) {
  let active = 0;
  let sequence = 0;
  const queued: QueuedTask[] = [];

  function drain() {
    while (active < limit && queued.length) {
      const task = queued.shift();
      if (!task) return;
      active += 1;
      void task.run().finally(() => {
        active -= 1;
        drain();
      });
    }
  }

  return {
    schedule<T>(load: () => Promise<T>, options: { signal?: AbortSignal; priority?: number } = {}): Promise<T> {
      return new Promise<T>((resolve, reject) => {
        if (options.signal?.aborted) {
          reject(abortError());
          return;
        }
        const task: QueuedTask = {
          priority: Number.isFinite(options.priority) ? options.priority ?? 0 : 0,
          sequence: sequence++,
          run: async () => {
            options.signal?.removeEventListener("abort", dropAbortedTask);
            if (options.signal?.aborted) {
              reject(abortError());
              return;
            }
            try {
              resolve(await load());
            } catch (error) {
              reject(error);
            }
          },
        };
        const dropAbortedTask = () => {
          const index = queued.indexOf(task);
          if (index === -1) return;
          queued.splice(index, 1);
          reject(abortError());
        };
        options.signal?.addEventListener("abort", dropAbortedTask, { once: true });
        const insertionIndex = queued.findIndex((candidate) => (
          candidate.priority < task.priority
          || (candidate.priority === task.priority && candidate.sequence > task.sequence)
        ));
        if (insertionIndex === -1) queued.push(task);
        else queued.splice(insertionIndex, 0, task);
        drain();
      });
    },
  };
}
