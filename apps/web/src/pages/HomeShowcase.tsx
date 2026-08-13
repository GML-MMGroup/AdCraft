import type { CSSProperties, RefObject } from "react";
import { demoProjects, images, imageSrc } from "../data";
import { DiscoverOrbit, type DiscoverOrbitItem } from "./DiscoverOrbit";
import { HeroAccentWriting } from "./HeroAccentWriting";

const homeProductPoster = "/assets/card1.webp";
const heroTitleLines = [
  "ONE SENTENCE",
  "BECOMES AN",
  "Ad film.",
] as const;
const discoverCards: readonly DiscoverOrbitItem[] = [
  { title: "Campaign Flow", image: imageSrc(images[0]) },
  { title: "Character Study", image: imageSrc(images[1]) },
  { title: "Poster Motion", image: imageSrc(images[2]) },
  { title: "Scene Extension", image: imageSrc(images[3]) },
  { title: "Product Aura", image: imageSrc(images[4]) },
  { title: "Editorial Cut", image: imageSrc(images[5]) },
  { title: "Portrait Spark", image: imageSrc(images[6]) },
  { title: "Color Script", image: imageSrc(images[7]) },
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

type HeroTitleMotionDirection = "left-to-right" | "right-to-left";

function heroCharacterStyle(motionOrder: number, canBump: boolean): CSSProperties {
  return {
    "--home-hero-character-index": String(motionOrder),
    ...(canBump ? { "--home-hero-character-bump-index": String(motionOrder + 1) } : {}),
  } as CSSProperties;
}

function HeroMainTitleLine({ line, direction }: { line: string; direction: HeroTitleMotionDirection }) {
  const characters = Array.from(line);

  return characters.map((character, characterIndex) => {
    const motionOrder = direction === "left-to-right"
      ? characterIndex
      : characters.length - characterIndex - 1;
    const canBump = motionOrder < characters.length - 1;

    return (
      <span
        key={`${character}-${characterIndex}`}
        className={`home-product-hero__title-character ${canBump ? "home-product-hero__title-character--bump" : ""}`}
        data-home-hero-character-order={motionOrder}
        style={heroCharacterStyle(motionOrder, canBump)}
      >
        <span className="home-product-hero__title-character__glyph">{character === " " ? "\u00a0" : character}</span>
      </span>
    );
  });
}

function HeroTitle({ useWritingAccent }: { useWritingAccent: boolean }) {
  return (
    <h1
      className="home-product-hero__title"
      id="home-product-title"
      aria-label="One Sentence Becomes an Ad film."
      data-home-typography-region="heroMain"
    >
      {heroTitleLines.map((line, lineIndex) => {
        const direction: HeroTitleMotionDirection | null = lineIndex === 0
          ? "left-to-right"
          : lineIndex === 1
            ? "right-to-left"
            : null;

        return (
          <span
            key={line}
            className={[
              "home-product-hero__title-line",
              direction ? `home-product-hero__title-line--${direction}` : "",
              lineIndex === 2 ? "home-product-hero__accent" : "",
              lineIndex === 2 && useWritingAccent ? "home-product-hero__accent--writing" : "",
            ].filter(Boolean).join(" ")}
            data-accent-text={lineIndex === 2 ? line : undefined}
            data-home-typography-region={lineIndex === 2 ? "heroAccent" : undefined}
            data-testid={lineIndex === 2 ? "home-hero-accent" : undefined}
            aria-hidden="true"
          >
            {lineIndex === 2 && useWritingAccent
              ? <HeroAccentWriting />
              : direction
                ? <HeroMainTitleLine line={line} direction={direction} />
                : line}
          </span>
        );
      })}
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
  return <DiscoverOrbit items={discoverCards} interactive onSelect={openPreview} />;
}

function StaticDiscover() {
  return <DiscoverOrbit items={discoverCards} interactive={false} />;
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
          <HeroTitle useWritingAccent={isInteractive} />
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
