import { useEffect, useRef, useState, type ImgHTMLAttributes } from "react";

import { cachedStableMediaUrl, isStableMediaUrl, loadStableMedia } from "./stableMediaCache.ts";

export type StableMediaPreviewProps = Omit<ImgHTMLAttributes<HTMLImageElement>, "src"> & {
  src?: string | null;
  /** Delay cache/network hydration so critical non-media UI can start first. */
  deferMs?: number;
};

/** Image preview with URL-level request dedupe and persistent versioned media cache. */
export function StableMediaPreview({ src, deferMs = 0, ...props }: StableMediaPreviewProps) {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [resolvedSource, setResolvedSource] = useState<string | null>(() => initialSource(src));

  useEffect(() => {
    let active = true;
    let started = false;
    let timerId: number | null = null;
    setResolvedSource(initialSource(src));
    if (!src) return () => { active = false; };

    const hydrate = () => {
      if (started) return;
      started = true;
      const load = () => loadStableMedia(src)
        .then((nextSource) => {
          if (active) setResolvedSource(nextSource);
        })
        .catch(() => {
          // Keep the canonical URL as a browser-native fallback when caching fails.
          if (active) setResolvedSource(src);
        });
      if (deferMs > 0) {
        timerId = window.setTimeout(() => {
          timerId = null;
          void load();
        }, deferMs);
      } else {
        void load();
      }
    };
    const image = imageRef.current;
    const shouldDefer = props.loading === "lazy"
      && typeof IntersectionObserver !== "undefined"
      && image !== null;
    if (shouldDefer && image) {
      const observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          observer.disconnect();
          hydrate();
        }
      }, { rootMargin: "240px" });
      observer.observe(image);
      return () => {
        active = false;
        observer.disconnect();
        if (timerId !== null) window.clearTimeout(timerId);
      };
    }
    hydrate();
    return () => {
      active = false;
      if (timerId !== null) window.clearTimeout(timerId);
    };
  }, [deferMs, props.loading, src]);

  return <img {...props} ref={imageRef} src={resolvedSource ?? undefined} />;
}

function initialSource(sourceUrl?: string | null): string | null {
  if (!sourceUrl) return null;
  return cachedStableMediaUrl(sourceUrl) ?? (isStableMediaUrl(sourceUrl) ? null : sourceUrl);
}
