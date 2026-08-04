type QueuedTask = {
  run: () => Promise<void>;
};

function abortError() {
  const error = new Error("Request aborted");
  error.name = "AbortError";
  return error;
}

export function createRequestQueue(limit: number) {
  let active = 0;
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
    schedule<T>(load: () => Promise<T>, options: { signal?: AbortSignal } = {}): Promise<T> {
      return new Promise<T>((resolve, reject) => {
        if (options.signal?.aborted) {
          reject(abortError());
          return;
        }
        const task: QueuedTask = {
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
        queued.push(task);
        drain();
      });
    },
  };
}
