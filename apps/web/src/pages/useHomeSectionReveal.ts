import { useEffect, useRef, useState } from "react";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

export function useHomeSectionReveal() {
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
        if (hasRevealed || !entries.some((entry) => entry.isIntersecting)) return;
        hasRevealed = true;
        setIsVisible(true);
        observer.disconnect();
      },
      {
        rootMargin: "0px 0px -12% 0px",
        threshold: 0.16,
      },
    );

    observer.observe(section);
    return () => observer.disconnect();
  }, []);

  return {
    sectionRef,
    revealState: isVisible ? "visible" : "pending",
  } as const;
}
