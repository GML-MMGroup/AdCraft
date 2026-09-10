import { lazy, Suspense, useEffect, useState } from "react";
import { useHealth } from "../app/useHealth";
import type { AppNavigate } from "../types";
import { HomeShowcase } from "./HomeShowcase";
import { HomeRecentLoading } from "./HomeRecentLoading";
import { useHomeHeroMotionReady } from "./useHomeHeroMotionReady";
import { useHomeSectionReveal } from "./useHomeSectionReveal";
import "./home.css";

const homeProductVideoUrl = import.meta.env.VITE_HOME_PRODUCT_VIDEO_URL?.trim()
  || "/assets/home-product-film.mp4";
const HomeRecentProjects = lazy(() => import("./home/HomeRecentProjects").then((module) => ({ default: module.HomeRecentProjects })));
const recentLoading = <HomeRecentLoading />;

export function HomePage({ navigate }: { navigate: AppNavigate }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [introVideoFailed, setIntroVideoFailed] = useState(false);
  const isHeroMotionReady = useHomeHeroMotionReady();
  const recentReveal = useHomeSectionReveal();
  const [recentEnabled, setRecentEnabled] = useState(false);
  const discoverReveal = useHomeSectionReveal({ replay: true });
  const { startNewProject } = useHealth();
  const hasIntroVideo = Boolean(homeProductVideoUrl) && !introVideoFailed;

  useEffect(() => {
    const section = recentReveal.sectionRef.current;
    if (!section) return;
    if (typeof IntersectionObserver === "undefined") {
      setRecentEnabled(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.target === section && entry.isIntersecting)) {
        setRecentEnabled(true);
        observer.disconnect();
      }
    }, { rootMargin: "320px" });
    observer.observe(section);
    return () => observer.disconnect();
  }, [recentReveal.sectionRef]);

  async function createProject() {
    await startNewProject();
    navigate("workflow", { state: { startNewProject: true } });
  }

  return (
    <HomeShowcase
      mode="interactive"
      heroMotionReady={isHeroMotionReady}
      recentReveal={recentReveal}
      discoverReveal={discoverReveal}
      hasIntroVideo={hasIntroVideo}
      productVideoUrl={homeProductVideoUrl}
      onProductVideoError={() => setIntroVideoFailed(true)}
      previewOpen={modalOpen}
      recentContent={(
        recentEnabled ? <Suspense fallback={recentLoading}>
          <HomeRecentProjects
            loadingContent={recentLoading}
            onOpenProject={(projectId) => navigate("workflow", { projectId })}
            onCreateProject={() => void createProject()}
          />
        </Suspense> : recentLoading
      )}
      interactions={{
        createProject: () => void createProject(),
        openPreview: () => setModalOpen(true),
        closePreview: () => setModalOpen(false),
      }}
    />
  );
}
