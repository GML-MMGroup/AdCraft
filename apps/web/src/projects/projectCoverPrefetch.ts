import { primeStableMedia } from "../workflow/stableMediaCache.ts";
import type { V2ProjectCover } from "./v2ProjectCover.ts";

const prefetchedUrls = new Set<string>();

/** Warm only visible project-card renditions; the browser still controls decoding. */
export function prefetchProjectCover(cover: V2ProjectCover | null | undefined, priority: number) {
  if (!cover || priority < 3) return;
  const url = cover.mediaType === "video" ? (cover.posterPath || cover.mediaPath) : cover.mediaPath;
  if (!url || prefetchedUrls.has(url)) return;
  prefetchedUrls.add(url);
  void primeStableMedia(url);
}

export function __resetProjectCoverPrefetchForTests() {
  prefetchedUrls.clear();
}
