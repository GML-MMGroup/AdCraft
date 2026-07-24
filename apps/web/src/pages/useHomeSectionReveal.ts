import { useEffect, useRef, useState } from "react";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const REVEAL_THRESHOLD = 0.16;

export function useHomeSectionReveal({ replay = false }: { replay?: boolean } = {}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    if (
      typeof window.matchMedia === "function"
      && window.matchMedia(REDUCED_MOTION_QUERY).matches
    ) {
      setIsVisible(true);
      return;
    }

    if (typeof IntersectionObserver === "undefined") {
      setIsVisible(true);
      return;
    }

    let hasRevealed = false;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries.find((candidate) => candidate.target === section);
        if (!entry) return;

        if (replay) {
          if (!entry.isIntersecting) {
            setIsVisible(false);
          } else if (entry.intersectionRatio >= REVEAL_THRESHOLD) {
            setIsVisible(true);
          }
          return;
        }

        if (
          hasRevealed
          || !entry.isIntersecting
          || entry.intersectionRatio < REVEAL_THRESHOLD
        ) return;
        hasRevealed = true;
        setIsVisible(true);
        observer.disconnect();
      },
      {
        rootMargin: "0px 0px -12% 0px",
        threshold: [0, REVEAL_THRESHOLD],
      },
    );

    observer.observe(section);
    return () => observer.disconnect();
  }, [replay]);

  return {
    sectionRef,
    revealState: isVisible ? "visible" : "pending",
  } as const;
}
