type QueuedTask = {
  run: () => Promise<void>;
};

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
    schedule<T>(load: () => Promise<T>): Promise<T> {
      return new Promise<T>((resolve, reject) => {
        queued.push({
          run: async () => {
            try {
              resolve(await load());
            } catch (error) {
              reject(error);
            }
          },
        });
        drain();
      });
    },
  };
}
