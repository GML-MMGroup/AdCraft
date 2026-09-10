type ReleaseVideoPreviewLoad = () => void;
type QueueEntry = (release: ReleaseVideoPreviewLoad) => void;

const queue: QueueEntry[] = [];
let active = false;

export function acquireCanvasVideoPreviewLoad() {
  return new Promise<ReleaseVideoPreviewLoad>((resolve) => {
    queue.push(resolve);
    drain();
  });
}

function drain() {
  if (active) return;
  const next = queue.shift();
  if (!next) return;
  active = true;
  let released = false;
  next(() => {
    if (released) return;
    released = true;
    active = false;
    drain();
  });
}
