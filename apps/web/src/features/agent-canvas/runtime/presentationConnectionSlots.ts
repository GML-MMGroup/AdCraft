// Leave browser HTTP/1 connections available for workflow events and normal reads.
// All presentation consumers (chat and node workbenches) share this limit.
const MAX_CONNECTIONS = 2;
const waiting: Array<() => void> = [];
let active = 0;

function drain() {
  while (active < MAX_CONNECTIONS && waiting.length) waiting.shift()!();
}

export function reservePresentationConnection(start: (release: () => void) => void): () => void {
  let acquired = false;
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    const index = waiting.indexOf(acquire);
    if (index !== -1) waiting.splice(index, 1);
    if (acquired) active -= 1;
    drain();
  };
  const acquire = () => {
    if (released) return;
    acquired = true;
    active += 1;
    start(release);
  };
  waiting.push(acquire);
  drain();
  return release;
}
