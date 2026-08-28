type VideoFrameRequest = {
  video: HTMLVideoElement;
  resolve: () => void;
};

const FIRST_FRAME_TIMEOUT_MS = 8_000;
const pendingRequests = new WeakMap<HTMLVideoElement, Promise<void>>();
const requestQueue: VideoFrameRequest[] = [];
let activeRequest = false;

export function requestNativeVideoFirstFrame(video: HTMLVideoElement) {
  const existingRequest = pendingRequests.get(video);
  if (existingRequest) return existingRequest;

  let resolveRequest: () => void = () => undefined;
  const request = new Promise<void>((resolve) => {
    resolveRequest = resolve;
  });
  pendingRequests.set(video, request);
  requestQueue.push({ video, resolve: resolveRequest });
  drainQueue();
  return request;
}

function drainQueue() {
  if (activeRequest) return;
  const next = requestQueue.shift();
  if (!next) return;

  activeRequest = true;
  const { video, resolve } = next;
  let settled = false;
  const finish = () => {
    if (settled) return;
    settled = true;
    video.removeEventListener("seeked", finish);
    video.removeEventListener("error", finish);
    window.clearTimeout(timeoutId);
    pendingRequests.delete(video);
    activeRequest = false;
    resolve();
    drainQueue();
  };
  const timeoutId = window.setTimeout(finish, FIRST_FRAME_TIMEOUT_MS);
  const duration = Number.isFinite(video.duration) ? video.duration : 0;
  const targetTime = duration > 0 ? Math.min(0.5, duration * 0.1) : 0;

  video.addEventListener("seeked", finish, { once: true });
  video.addEventListener("error", finish, { once: true });

  if (!targetTime || (video.readyState >= 3 && Math.abs(video.currentTime - targetTime) < 0.001)) {
    finish();
    return;
  }

  try {
    video.currentTime = targetTime;
  } catch {
    finish();
  }
}
