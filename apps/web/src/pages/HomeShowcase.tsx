import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
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

type HeroQueueCharacter = {
  characterIndex: number;
  motionOrder: number;
  slotIndex: number;
};

type HeroQueueDirection = "from-left" | "from-right";

function createHeroQueueCharacters(
  line: string,
  direction: HeroQueueDirection,
): HeroQueueCharacter[] {
  const characters = Array.from(line);
  const motionOrderByCharacterIndex = new Map<number, number>();
  let motionOrder = 0;

  const startIndex = direction === "from-left" ? characters.length - 1 : 0;
  const endIndex = direction === "from-left" ? -1 : characters.length;
  const step = direction === "from-left" ? -1 : 1;
  for (
    let characterIndex = startIndex;
    characterIndex !== endIndex;
    characterIndex += step
  ) {
    if (characters[characterIndex] !== " ") {
      motionOrderByCharacterIndex.set(characterIndex, motionOrder);
      motionOrder += 1;
    }
  }

  let slotIndex = 0;
  return characters.flatMap((character, characterIndex) => {
    if (character === " ") return [];

    const queueCharacter: HeroQueueCharacter = {
      characterIndex,
      motionOrder: motionOrderByCharacterIndex.get(characterIndex) ?? 0,
      slotIndex,
    };
    slotIndex += 1;
    return [queueCharacter];
  });
}

function useHeroQueueStartOffsets(
  lineRef: RefObject<HTMLSpanElement | null>,
  characterRefs: RefObject<(HTMLSpanElement | null)[]>,
  characterCount: number,
  direction: HeroQueueDirection,
) {
  const [startOffsets, setStartOffsets] = useState<number[]>([]);

  const measure = useCallback(() => {
    const line = lineRef.current;
    if (!line) return;

    const lineRect = line.getBoundingClientRect();
    const origin = direction === "from-left" ? lineRect.left : lineRect.right;
    const nextOffsets = Array.from({ length: characterCount }, (_, slotIndex) => {
      const character = characterRefs.current[slotIndex];
      if (!character) return null;

      const characterRect = character.getBoundingClientRect();
      return direction === "from-left"
        ? origin - characterRect.left
        : origin - characterRect.right;
    });
    if (nextOffsets.some((offset) => offset === null)) return;

    const measuredOffsets = nextOffsets as number[];
    setStartOffsets((previousOffsets) => {
      const hasChanged = previousOffsets.length !== measuredOffsets.length
        || previousOffsets.some((offset, index) => Math.abs(offset - measuredOffsets[index]!) > 0.1);
      return hasChanged ? measuredOffsets : previousOffsets;
    });
  }, [characterCount, characterRefs, direction, lineRef]);

  useLayoutEffect(() => {
    const line = lineRef.current;
    if (!line) return;

    measure();
    const resizeObserver = typeof ResizeObserver === "undefined"
      ? undefined
      : new ResizeObserver(measure);
    resizeObserver?.observe(line);
    window.addEventListener("resize", measure);

    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [lineRef, measure]);

  return startOffsets;
}

function heroCharacterStyle(
  motionOrder: number,
  startOffset: number | undefined,
): CSSProperties {
  return {
    "--home-hero-character-index": String(motionOrder),
    "--home-hero-character-start-offset": `${startOffset ?? 0}px`,
  } as CSSProperties;
}

function HeroMainTitleLine({ line, direction }: { line: string; direction: HeroQueueDirection }) {
  const characters = Array.from(line);
  const queueCharacters = createHeroQueueCharacters(line, direction);
  const queueCharacterByIndex = new Map(
    queueCharacters.map((queueCharacter) => [queueCharacter.characterIndex, queueCharacter]),
  );
  const lineRef = useRef<HTMLSpanElement>(null);
  const characterRefs = useRef<(HTMLSpanElement | null)[]>([]);
  const startOffsets = useHeroQueueStartOffsets(
    lineRef,
    characterRefs,
    queueCharacters.length,
    direction,
  );
  const isQueueReady = startOffsets.length === queueCharacters.length;

  return (
    <span
      ref={lineRef}
      className="home-product-hero__title-line home-product-hero__title-line--queue"
      data-home-hero-queue-origin={direction === "from-left" ? "line-start" : "line-end"}
      data-home-hero-queue-ready={isQueueReady ? "true" : "false"}
      aria-hidden="true"
    >
      {characters.map((character, characterIndex) => {
        if (character === " ") return "\u00a0";

        const queueCharacter = queueCharacterByIndex.get(characterIndex);
        if (!queueCharacter) return null;

        return (
          <span
            key={`${character}-${characterIndex}`}
            ref={(element) => {
              characterRefs.current[queueCharacter.slotIndex] = element;
            }}
            className="home-product-hero__title-character"
            data-home-hero-character-order={queueCharacter.motionOrder}
            style={heroCharacterStyle(
              queueCharacter.motionOrder,
              startOffsets[queueCharacter.slotIndex],
            )}
          >
            <span className="home-product-hero__title-character__glyph">{character}</span>
          </span>
        );
      })}
    </span>
  );
}

function HeroTitle({ useWritingAccent }: { useWritingAccent: boolean }) {
  return (
    <h1
      className="home-product-hero__title"
      id="home-product-title"
      aria-label="One Sentence Becomes an Ad film."
      data-home-typography-region="heroMain"
    >
      <HeroMainTitleLine line={heroTitleLines[0]} direction="from-left" />
      <HeroMainTitleLine line={heroTitleLines[1]} direction="from-right" />
      <span
        className={[
          "home-product-hero__title-line",
          "home-product-hero__accent",
          useWritingAccent ? "home-product-hero__accent--writing" : "",
        ].filter(Boolean).join(" ")}
        data-accent-text={heroTitleLines[2]}
        data-home-typography-region="heroAccent"
        data-testid="home-hero-accent"
        aria-hidden="true"
      >
        {useWritingAccent ? <HeroAccentWriting /> : heroTitleLines[2]}
      </span>
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
