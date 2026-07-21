import { useEffect, useRef, useState, type VideoHTMLAttributes } from "react";

type DeferredVideoProps = Omit<VideoHTMLAttributes<HTMLVideoElement>, "preload" | "src"> & {
  src: string;
  preload?: "none" | "metadata" | "auto";
  eager?: boolean;
  rootMargin?: string;
};

/** Keeps offscreen card previews from opening video connections until needed. */
export function DeferredVideo({
  src,
  preload = "metadata",
  eager = false,
  rootMargin = "640px",
  onFocus,
  onPointerEnter,
  ...videoProps
}: DeferredVideoProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [loadedSrc, setLoadedSrc] = useState(eager ? src : "");
  const shouldLoad = eager || loadedSrc === src;

  useEffect(() => {
    if (eager) {
      setLoadedSrc(src);
      return;
    }
    setLoadedSrc("");
    const element = videoRef.current;
    if (!element || typeof IntersectionObserver === "undefined") {
      setLoadedSrc(src);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setLoadedSrc(src);
        observer.disconnect();
      },
      { rootMargin },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [eager, rootMargin, src]);

  const reveal = () => setLoadedSrc(src);
  return (
    <video
      {...videoProps}
      ref={videoRef}
      src={shouldLoad ? src : undefined}
      preload={shouldLoad ? preload : "none"}
      onFocus={(event) => {
        reveal();
        onFocus?.(event);
      }}
      onPointerEnter={(event) => {
        reveal();
        onPointerEnter?.(event);
      }}
    />
  );
}
