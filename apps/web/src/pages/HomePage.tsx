import { useState } from "react";
import type { CSSProperties } from "react";
import { useApp } from "../AppContextValue";
import { SectionTitle } from "../components/Cards";
import { demoProjects, images, imageSrc } from "../data";
import { PlayIcon, PlusIcon } from "../icons";
import type { RouteName } from "../types";
import { useHomeHeroMotionReady } from "./useHomeHeroMotionReady";
import { useHomeSectionReveal } from "./useHomeSectionReveal";

const homeProductVideoUrl = import.meta.env.VITE_HOME_PRODUCT_VIDEO_URL?.trim();
const homeProductPoster = "/assets/card1.webp";
const heroTitleLines = [
  "One Sentence",
  "Becomes an",
  "Ad film.",
] as const;
const HERO_CHARACTER_START_DELAY_MS = 80;
const HERO_CHARACTER_STAGGER_MS = 28;
const heroLineCharacterOffsets = heroTitleLines.map((_, lineIndex) => (
  heroTitleLines
    .slice(0, lineIndex)
    .reduce((offset, line) => offset + Array.from(line).length, 0)
));

type HeroCharacterStyle = CSSProperties & {
  "--home-character-delay": string;
  "--home-accent-position"?: string;
};

function motionStyle(property: "--home-reveal-delay", value: string): CSSProperties {
  return { [property]: value } as CSSProperties;
}

function heroCharacterStyle(
  characterIndex: number,
  accentIndex?: number,
  accentLength?: number,
): HeroCharacterStyle {
  const style: HeroCharacterStyle = {
    "--home-character-delay": `${
      HERO_CHARACTER_START_DELAY_MS + characterIndex * HERO_CHARACTER_STAGGER_MS
    }ms`,
  };

  if (accentIndex !== undefined && accentLength !== undefined) {
    const finalAccentIndex = Math.max(1, accentLength - 1);
    style["--home-accent-position"] = `${
      (accentIndex / finalAccentIndex) * 100
    }%`;
  }

  return style;
}

export function HomePage({ navigate }: { navigate: (route: RouteName) => void }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [introVideoFailed, setIntroVideoFailed] = useState(false);
  const isHeroMotionReady = useHomeHeroMotionReady();
  const recentReveal = useHomeSectionReveal();
  const discoverReveal = useHomeSectionReveal({ replay: true });
  const { startNewProject } = useApp();
  const hasIntroVideo = Boolean(homeProductVideoUrl) && !introVideoFailed;

  const discoverCards: Array<[string, string, number]> = [
    ["Campaign Flow", images[0], 240],
    ["Character Study", images[1], 330],
    ["Poster Motion", images[2], 260],
    ["Scene Extension", images[3], 370],
    ["Product Aura", images[4], 280],
    ["Editorial Cut", images[5], 320],
    ["Portrait Spark", images[6], 260],
    ["Color Script", images[7], 350],
  ];

  function createProject() {
    startNewProject();
    navigate("workflow");
  }

  return (
    <div className="home-page">
      <section
        className={`home-product-hero ${isHeroMotionReady ? "is-motion-ready" : ""}`}
        aria-labelledby="home-product-title"
      >
        <div className="home-product-hero__content">
          <h1 className="home-product-hero__title" id="home-product-title" aria-label="One Sentence Becomes an Ad film.">
            {heroTitleLines.map((line, lineIndex) => (
              <span
                key={line}
                className={`home-product-hero__title-line ${lineIndex === 2 ? "home-product-hero__accent" : ""}`}
                aria-hidden="true"
              >
                {Array.from(line).map((character, characterIndex) => {
                  const globalCharacterIndex = (
                    heroLineCharacterOffsets[lineIndex] + characterIndex
                  );
                  const isSpace = character === " ";

                  return (
                    <span
                      key={`${lineIndex}-${characterIndex}`}
                      className={`home-product-hero__character ${isSpace ? "home-product-hero__character--space" : ""}`}
                      data-character-index={globalCharacterIndex}
                      style={heroCharacterStyle(
                        globalCharacterIndex,
                        lineIndex === 2 ? characterIndex : undefined,
                        lineIndex === 2 ? Array.from(line).length : undefined,
                      )}
                    >
                      <span className={`home-product-hero__glyph ${lineIndex === 2 ? "home-product-hero__accent-glyph" : ""}`}>
                        {character}
                      </span>
                    </span>
                  );
                })}
              </span>
            ))}
          </h1>
          <p className="home-product-hero__description">
            AdCraft — The first agentic video production platform for marketing and advertising. Infinite canvas · shot-by-shot replication · fully automated, from idea to final cut.
          </p>
          <div className="home-product-hero__create-stage">
            <button className="home-product-hero__create" type="button" onClick={createProject}>
              <PlusIcon />
              <span>Create Your Project</span>
            </button>
          </div>
        </div>

        <div className="home-product-film" aria-label="AdCraft product introduction media" data-media-slot="product-introduction">
          {hasIntroVideo ? (
            <video
              src={homeProductVideoUrl}
              autoPlay
              loop
              muted
              playsInline
              preload="metadata"
              poster={homeProductPoster}
              onError={() => setIntroVideoFailed(true)}
            />
          ) : (
            <img src={homeProductPoster} alt="" />
          )}
        </div>
      </section>

      <div className="content-wrap">
        <section
          ref={recentReveal.sectionRef}
          className="home-reveal-section home-reveal-section--recent"
          data-reveal-state={recentReveal.revealState}
          aria-label="Recent Projects"
        >
          <div data-reveal-item style={motionStyle("--home-reveal-delay", "0ms")}>
            <SectionTitle title="Recent Projects" subtitle="Pick up the latest creative thread." />
          </div>
          <div className="recent-strip" data-reveal-item style={motionStyle("--home-reveal-delay", "100ms")}>
            <button
              className="recent-card featured"
              data-reveal-item
              style={motionStyle("--home-reveal-delay", "170ms")}
              onClick={() => navigate("workflow")}
            >
              <div className="featured-glass">
                <h3>New fragrance product reel</h3>
                <p>Continue editing the current workflow canvas.</p>
              </div>
            </button>
            {demoProjects.slice(0, 3).map((project, index) => (
              <button
                key={project.name}
                className="recent-card"
                data-reveal-item
                style={motionStyle("--home-reveal-delay", `${240 + index * 70}ms`)}
                onClick={() => navigate("workflow")}
              >
                <h3>{project.name}</h3>
                <p>{project.time}</p>
              </button>
            ))}
          </div>
        </section>

        <section
          ref={discoverReveal.sectionRef}
          className="home-reveal-section home-reveal-section--discover"
          data-reveal-state={discoverReveal.revealState}
          aria-label="Discover"
        >
          <div data-reveal-item style={motionStyle("--home-reveal-delay", "0ms")}>
            <SectionTitle title="Discover" subtitle="References, templates, and generated video ideas." />
          </div>
          <div className="discover-tabs" data-reveal-item style={motionStyle("--home-reveal-delay", "100ms")}>
            {["All", "Product", "Portrait", "Scene", "Motion"].map((tab, index) => (
              <button key={tab} className={`filter-btn ${index === 0 ? "is-active" : ""}`}>
                {tab}
              </button>
            ))}
          </div>
          <div className="waterfall">
            {discoverCards.map(([title, img, height], index) => (
              <button
                key={title}
                className="discover-card"
                style={{
                  "--h": `${height}px`,
                  "--home-reveal-delay": `${170 + index * 65}ms`,
                } as CSSProperties}
                data-title={title}
                data-reveal-item
                onClick={() => setModalOpen(true)}
              >
                <img className="discover-card-image" src={imageSrc(img)} alt="" loading="lazy" decoding="async" />
                <span className="play-dot">
                  <span>
                    <PlayIcon />
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <div className={`video-modal ${modalOpen ? "is-open" : ""}`}>
        <div className="modal-card">
          <div className="modal-preview">
            <PlayIcon />
          </div>
          <div className="composer-footer" style={{ marginTop: 14 }}>
            <strong>Preview Case</strong>
            <button className="small-action" onClick={() => setModalOpen(false)}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
