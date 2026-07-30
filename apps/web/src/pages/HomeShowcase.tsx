import type { CSSProperties, RefObject } from "react";
import { demoProjects, images, imageSrc } from "../data";

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

type RevealState = "pending" | "visible";

type RevealSection = {
  sectionRef?: RefObject<HTMLElement | null>;
  revealState?: RevealState;
};

type HomeShowcaseInteractions = {
  createProject: () => void;
  openWorkflow: () => void;
  openPreview: () => void;
  closePreview: () => void;
};

export type HomeShowcaseProps = {
  mode: "interactive" | "static";
  interactions?: HomeShowcaseInteractions;
  heroMotionReady?: boolean;
  recentReveal?: RevealSection;
  discoverReveal?: RevealSection;
  hasIntroVideo?: boolean;
  productVideoUrl?: string;
  onProductVideoError?: () => void;
  previewOpen?: boolean;
};

type HeroCharacterStyle = CSSProperties & {
  "--home-character-delay": string;
};

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="section-title">
      <h2 data-home-typography-region="sectionHeading">{title}</h2>
      <p data-home-typography-region="sectionBody">{subtitle}</p>
    </div>
  );
}

function motionStyle(property: "--home-reveal-delay", value: string): CSSProperties {
  return { [property]: value } as CSSProperties;
}

function heroCharacterStyle(characterIndex: number): HeroCharacterStyle {
  return {
    "--home-character-delay": `${HERO_CHARACTER_START_DELAY_MS + characterIndex * HERO_CHARACTER_STAGGER_MS}ms`,
  };
}

function HeroTitle() {
  return (
    <h1
      className="home-product-hero__title"
      id="home-product-title"
      aria-label="One Sentence Becomes an Ad film."
      data-home-typography-region="heroMain"
    >
      {heroTitleLines.map((line, lineIndex) => (
        <span
          key={line}
          className={`home-product-hero__title-line ${lineIndex === 2 ? "home-product-hero__accent" : ""}`}
          data-accent-text={lineIndex === 2 ? line : undefined}
          data-home-typography-region={lineIndex === 2 ? "heroAccent" : undefined}
          data-testid={lineIndex === 2 ? "home-hero-accent" : undefined}
          aria-hidden="true"
        >
          {Array.from(line).map((character, characterIndex) => {
            const globalCharacterIndex = heroLineCharacterOffsets[lineIndex] + characterIndex;
            const isSpace = character === " ";

            return (
              <span
                key={`${lineIndex}-${characterIndex}`}
                className={`home-product-hero__character ${isSpace ? "home-product-hero__character--space" : ""}`}
                data-character-index={globalCharacterIndex}
                style={heroCharacterStyle(globalCharacterIndex)}
              >
                <span className="home-product-hero__glyph">{character}</span>
              </span>
            );
          })}
        </span>
      ))}
    </h1>
  );
}

function InteractiveRecentCards({ openWorkflow }: { openWorkflow: () => void }) {
  return (
    <div className="recent-strip" data-reveal-item style={motionStyle("--home-reveal-delay", "100ms")}>
      <button
        className="recent-card featured"
        data-reveal-item
        style={motionStyle("--home-reveal-delay", "170ms")}
        onClick={openWorkflow}
      >
        <div className="featured-glass">
          <h3 data-home-typography-region="cardTitle">New fragrance product reel</h3>
          <p data-home-typography-region="cardMeta">Continue editing the current workflow canvas.</p>
        </div>
      </button>
      {demoProjects.slice(0, 3).map((project, index) => (
        <button
          key={project.name}
          className="recent-card"
          data-reveal-item
          style={motionStyle("--home-reveal-delay", `${240 + index * 70}ms`)}
          onClick={openWorkflow}
        >
          <h3 data-home-typography-region="cardTitle">{project.name}</h3>
          <p data-home-typography-region="cardMeta">{project.time}</p>
        </button>
      ))}
    </div>
  );
}

function StaticRecentCards() {
  return (
    <div className="recent-strip" data-reveal-item style={motionStyle("--home-reveal-delay", "100ms")}>
      <article className="recent-card featured" data-reveal-item style={motionStyle("--home-reveal-delay", "170ms")}>
        <div className="featured-glass">
          <h3 data-home-typography-region="cardTitle">New fragrance product reel</h3>
          <p data-home-typography-region="cardMeta">Continue editing the current workflow canvas.</p>
        </div>
      </article>
      {demoProjects.slice(0, 3).map((project, index) => (
        <article
          key={project.name}
          className="recent-card"
          data-reveal-item
          style={motionStyle("--home-reveal-delay", `${240 + index * 70}ms`)}
        >
          <h3 data-home-typography-region="cardTitle">{project.name}</h3>
          <p data-home-typography-region="cardMeta">{project.time}</p>
        </article>
      ))}
    </div>
  );
}

function InteractiveDiscover({ openPreview }: { openPreview: () => void }) {
  return (
    <>
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
            data-home-typography-region="cardTitle"
            data-reveal-item
            onClick={openPreview}
          >
            <img className="discover-card-image" src={imageSrc(img)} alt="" loading="lazy" decoding="async" />
            <span className="play-dot">
              <span><span aria-hidden="true">▶</span></span>
            </span>
          </button>
        ))}
      </div>
    </>
  );
}

function StaticDiscover() {
  return (
    <>
      <div className="discover-tabs" data-reveal-item style={motionStyle("--home-reveal-delay", "100ms")}>
        {["All", "Product", "Portrait", "Scene", "Motion"].map((tab, index) => (
          <span key={tab} className={`filter-btn ${index === 0 ? "is-active" : ""}`} data-home-typography-region="navigation">
            {tab}
          </span>
        ))}
      </div>
      <div className="waterfall">
        {discoverCards.map(([title, img, height], index) => (
          <article
            key={title}
            className="discover-card"
            style={{
              "--h": `${height}px`,
              "--home-reveal-delay": `${170 + index * 65}ms`,
            } as CSSProperties}
            data-title={title}
            data-home-typography-region="cardTitle"
            data-reveal-item
          >
            <img className="discover-card-image" src={imageSrc(img)} alt="" loading="lazy" decoding="async" />
          </article>
        ))}
      </div>
    </>
  );
}

export function HomeShowcase({
  mode,
  interactions,
  heroMotionReady = false,
  recentReveal,
  discoverReveal,
  hasIntroVideo = false,
  productVideoUrl,
  onProductVideoError,
  previewOpen = false,
}: HomeShowcaseProps) {
  const isInteractive = mode === "interactive";
  const recentState = recentReveal?.revealState ?? "visible";
  const discoverState = discoverReveal?.revealState ?? "visible";

  return (
    <div className={`home-page home-page--${mode}`}>
      <section
        className={`home-product-hero ${heroMotionReady ? "is-motion-ready" : ""}`}
        aria-labelledby="home-product-title"
      >
        <div className="home-product-hero__content">
          <HeroTitle />
          <p className="home-product-hero__description" data-home-typography-region="heroBody">
            AdCraft — The first agentic video production platform for marketing and advertising. Infinite canvas · shot-by-shot replication · fully automated, from idea to final cut.
          </p>
          <div className="home-product-hero__create-stage">
            {isInteractive && interactions ? (
              <button className="home-product-hero__create" type="button" onClick={interactions.createProject} data-home-typography-region="heroAction">
                <span aria-hidden="true">+</span>
                <span>Create Your Project</span>
              </button>
            ) : (
              <span className="home-product-hero__create home-product-hero__create--static" data-home-typography-region="heroAction">
                <span aria-hidden="true">+</span>
                <span>Create Your Project</span>
              </span>
            )}
          </div>
        </div>

        <div className="home-product-film" aria-label="AdCraft product introduction media" data-media-slot="product-introduction">
          {isInteractive && hasIntroVideo && productVideoUrl ? (
            <video
              src={productVideoUrl}
              autoPlay
              loop
              muted
              playsInline
              preload="metadata"
              poster={homeProductPoster}
              onError={onProductVideoError}
            />
          ) : (
            <img src={homeProductPoster} alt="" />
          )}
        </div>
      </section>

      <div className="content-wrap">
        <section
          ref={recentReveal?.sectionRef}
          className="home-reveal-section home-reveal-section--recent"
          data-reveal-state={recentState}
          aria-label="Recent Projects"
        >
          <div data-reveal-item style={motionStyle("--home-reveal-delay", "0ms")}>
            <SectionTitle title="Recent Projects" subtitle="Pick up the latest creative thread." />
          </div>
          {isInteractive && interactions ? <InteractiveRecentCards openWorkflow={interactions.openWorkflow} /> : <StaticRecentCards />}
        </section>

        <section
          ref={discoverReveal?.sectionRef}
          className="home-reveal-section home-reveal-section--discover"
          data-reveal-state={discoverState}
          aria-label="Discover"
        >
          <div data-reveal-item style={motionStyle("--home-reveal-delay", "0ms")}>
            <SectionTitle title="Discover" subtitle="References, templates, and generated video ideas." />
          </div>
          {isInteractive && interactions ? <InteractiveDiscover openPreview={interactions.openPreview} /> : <StaticDiscover />}
        </section>
      </div>

      {isInteractive && interactions ? (
        <div className={`video-modal ${previewOpen ? "is-open" : ""}`}>
          <div className="modal-card">
            <div className="modal-preview"><span aria-hidden="true">▶</span></div>
            <div className="composer-footer" style={{ marginTop: 14 }}>
              <strong>Preview Case</strong>
              <button className="small-action" type="button" onClick={interactions.closePreview}>Close</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
