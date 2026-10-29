import { useEffect, useRef, useState } from "react";

function findScrollRoot(element: HTMLElement) {
  for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY)) return parent;
  }
  return null;
}

export function useHomeHeroVideo(interactive: boolean, hasVideo: boolean, videoUrl?: string) {
  const heroRef = useRef<HTMLElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [reducedMotion, setReducedMotion] = useState(() => (
    typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ));
  const [videoReady, setVideoReady] = useState(false);
  const [failedVideoUrl, setFailedVideoUrl] = useState<string>();
  const [muted, setMuted] = useState(true);
  const videoEnabled = interactive && hasVideo && Boolean(videoUrl)
    && !reducedMotion && failedVideoUrl !== videoUrl;

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    // Cached media can settle before React receives its load or error event.
    const video = videoRef.current;
    setVideoReady(Boolean(video && video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA));
    setMuted(true);
    if (video?.error) setFailedVideoUrl(videoUrl);
  }, [videoEnabled, videoUrl]);

  useEffect(() => {
    const hero = heroRef.current;
    const content = contentRef.current;
    if (!hero || !interactive || reducedMotion) return;

    const scrollRoot = findScrollRoot(hero);
    const scrollTarget = scrollRoot ?? window;
    const video = videoRef.current;
    let frame: number | undefined;

    function updateProgress() {
      frame = undefined;
      if (!hero) return;
      const bounds = hero.getBoundingClientRect();
      const rootTop = scrollRoot ? scrollRoot.getBoundingClientRect().top + scrollRoot.clientTop : 0;
      const progress = Math.min(1, Math.max(0, (rootTop - bounds.top) / Math.max(1, bounds.height)));
      hero.style.setProperty("--hero-progress", String(progress));
      if (content) content.inert = progress >= 0.6;
    }

    function queueUpdate() {
      if (frame === undefined) frame = window.requestAnimationFrame(updateProgress);
    }

    updateProgress();
    scrollTarget.addEventListener("scroll", queueUpdate, { passive: true });
    window.addEventListener("resize", queueUpdate);
    const resizeObserver = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(queueUpdate);
    resizeObserver?.observe(hero);
    if (scrollRoot) resizeObserver?.observe(scrollRoot);

    const observer = video && typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver((entries) => {
        const entry = entries.find((item) => item.target === hero);
        if (!entry) return;
        if (entry.isIntersecting) {
          if (video.paused) void video.play().catch(() => undefined);
        } else {
          video.pause();
          video.muted = true;
          setMuted(true);
        }
      }, { root: scrollRoot, threshold: 0 })
      : undefined;
    observer?.observe(hero);

    return () => {
      scrollTarget.removeEventListener("scroll", queueUpdate);
      window.removeEventListener("resize", queueUpdate);
      if (frame !== undefined) window.cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      observer?.disconnect();
      video?.pause();
      hero.style.setProperty("--hero-progress", "0");
      if (content) content.inert = false;
    };
  }, [interactive, reducedMotion, videoEnabled, videoUrl]);

  function toggleMuted() {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setMuted(video.muted);
    if (video.paused) void video.play().catch(() => undefined);
  }

  return {
    heroRef,
    contentRef,
    videoRef,
    reducedMotion,
    videoEnabled,
    videoReady,
    muted,
    toggleMuted,
    onVideoReady: () => setVideoReady(true),
    onVideoError: () => setFailedVideoUrl(videoUrl),
  };
}
