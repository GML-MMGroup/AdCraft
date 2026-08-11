import { useState } from "react";
import { useHealth } from "../app/useHealth";
import type { RouteName } from "../types";
import { HomeShowcase } from "./HomeShowcase";
import { useHomeHeroMotionReady } from "./useHomeHeroMotionReady";
import { useHomeSectionReveal } from "./useHomeSectionReveal";
import "./home.css";

const homeProductVideoUrl = import.meta.env.VITE_HOME_PRODUCT_VIDEO_URL?.trim()
  || "/assets/home-product-film.mp4";

export function HomePage({ navigate }: { navigate: (route: RouteName, options?: { state?: unknown }) => void }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [introVideoFailed, setIntroVideoFailed] = useState(false);
  const isHeroMotionReady = useHomeHeroMotionReady();
  const recentReveal = useHomeSectionReveal();
  const discoverReveal = useHomeSectionReveal({ replay: true });
  const { startNewProject } = useHealth();
  const hasIntroVideo = Boolean(homeProductVideoUrl) && !introVideoFailed;

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
      interactions={{
        createProject: () => void createProject(),
        openWorkflow: () => navigate("workflow"),
        openPreview: () => setModalOpen(true),
        closePreview: () => setModalOpen(false),
      }}
    />
  );
}
