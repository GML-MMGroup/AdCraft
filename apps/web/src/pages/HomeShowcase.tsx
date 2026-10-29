import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
  type ReactNode,
} from "react";
import { demoProjects, images, imageSrc } from "../data";
import { DiscoverOrbit, type DiscoverOrbitItem } from "./DiscoverOrbit";
import { FONT_CATALOG } from "../features/home-typography/fontCatalog";
import { loadWebFont } from "../features/home-typography/webFontLoader";
import { useLocale, localeText } from "../i18n/locale.tsx";
import { useHomeHeroVideo } from "./useHomeHeroVideo";

const homeProductPoster = "/assets/home-hero-poster.webp";
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
const discoverCardsZh = ["广告流程", "角色研究", "海报动效", "场景延展", "产品光感", "编辑剪辑", "肖像火花", "色彩脚本"];

type RevealState = "pending" | "visible";

type RevealSection = {
  sectionRef?: RefObject<HTMLElement | null>;
  revealState?: RevealState;
};

type HomeShowcaseInteractions = {
  createProject: () => void;
  openPreview: () => void;
  closePreview: () => void;
};

export type HomeShowcaseProps = {
  mode: "interactive" | "static";
  interactions?: HomeShowcaseInteractions;
  heroMotionReady?: boolean;
  recentReveal?: RevealSection;
  recentContent?: ReactNode;
  discoverReveal?: RevealSection;
  hasIntroVideo?: boolean;
  productVideoUrl?: string;
  onProductVideoError?: () => void;
  previewOpen?: boolean;
};

function SectionTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="section-title">
      <h2 data-home-typography-region="sectionHeading">{title}</h2>
      {subtitle && <p data-home-typography-region="sectionBody">{subtitle}</p>}
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

function HeroTitle() {
  const { locale } = useLocale();
  // Keep the editorial hero lockup in English in both locales; supporting
  // navigation and product copy still follow the selected UI language.
  const titleLines = heroTitleLines;
  const titleAriaLabel = "One Sentence Becomes an Ad film.";
  return (
    <h1
      className="home-product-hero__title"
      id="home-product-title"
      aria-label={titleAriaLabel}
      data-home-typography-region="heroMain"
    >
      <HeroMainTitleLine line={titleLines[0]} direction="from-left" />
      <HeroMainTitleLine line={titleLines[1]} direction="from-right" />
      <span
        className="home-product-hero__title-line home-product-hero__accent"
        data-accent-text={titleLines[2]}
        data-home-hero-accent-reveal="diagonal"
        data-home-typography-region="heroAccent"
        data-testid="home-hero-accent"
        aria-hidden="true"
      >
        {titleLines[2]}
      </span>
    </h1>
  );
}

function CreateProjectButtonContent({ label }: { label: string }) {
  return (
    <>
      <svg
        className="home-product-hero__create-icon"
        aria-hidden="true"
        viewBox="0 0 256 256"
      >
        <path d="M220,128a4,4,0,0,1-4,4H132v84a4,4,0,0,1-8,0V132H40a4,4,0,0,1,0-8h84V40a4,4,0,0,1,8,0v84h84A4,4,0,0,1,220,128Z" />
      </svg>
      <span>{label}</span>
    </>
  );
}

function StaticRecentCards() {
  const { locale } = useLocale();
  const labels = locale === "zh-CN" ? localeText.zh.homePage : localeText.en.homePage;
  return (
    <div className="recent-strip" data-reveal-item style={motionStyle("--home-reveal-delay", "100ms")}>
      <article className="recent-card featured" data-reveal-item style={motionStyle("--home-reveal-delay", "170ms")}>
        <div className="featured-glass">
          <h3 data-home-typography-region="cardTitle">{locale === "zh-CN" ? "全新香氛产品短片" : "New fragrance product reel"}</h3>
          <p data-home-typography-region="cardMeta">{labels.continueEditing}</p>
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
  const { locale } = useLocale();
  const items = locale === "zh-CN"
    ? discoverCards.map((card, index) => ({ ...card, title: discoverCardsZh[index] ?? card.title }))
    : discoverCards;
  return <DiscoverOrbit items={items} interactive onSelect={openPreview} />;
}

function StaticDiscover() {
  const { locale } = useLocale();
  const items = locale === "zh-CN"
    ? discoverCards.map((card, index) => ({ ...card, title: discoverCardsZh[index] ?? card.title }))
    : discoverCards;
  return <DiscoverOrbit items={items} interactive={false} />;
}

export function HomeShowcase({
  mode,
  interactions,
  heroMotionReady = false,
  recentReveal,
  recentContent,
  discoverReveal,
  hasIntroVideo = false,
  productVideoUrl,
  onProductVideoError,
  previewOpen = false,
}: HomeShowcaseProps) {
  const { locale } = useLocale();
  const labels = locale === "zh-CN" ? localeText.zh.homePage : localeText.en.homePage;
  const isInteractive = mode === "interactive";
  const recentState = recentReveal?.revealState ?? "visible";
  const discoverState = discoverReveal?.revealState ?? "visible";
  const heroVideo = useHomeHeroVideo(isInteractive, hasIntroVideo, productVideoUrl);

  useEffect(() => {
    const cardTitleFont = FONT_CATALOG.find((font) => font.id === "libre-baskerville");
    if (cardTitleFont) void loadWebFont(cardTitleFont).catch(() => undefined);
  }, []);

  return (
    <div className={`home-page home-page--${mode}`}>
      <section
        ref={heroVideo.heroRef}
        className={`home-product-hero ${isInteractive && !heroVideo.reducedMotion ? "is-motion-enabled" : ""} ${heroMotionReady && !heroVideo.reducedMotion ? "is-motion-ready" : ""}`}
        aria-labelledby="home-product-title"
      >
        <div className="home-product-hero__media" data-video-ready={heroVideo.videoReady ? "true" : "false"} aria-hidden="true">
          <div className="home-product-hero__visual">
            <img className="home-product-hero__poster" src={homeProductPoster} alt="" fetchPriority="high" />
            {heroVideo.videoEnabled ? (
              <video
                ref={heroVideo.videoRef}
                className="home-product-hero__video"
                src={productVideoUrl}
                autoPlay
                loop
                muted={heroVideo.muted}
                playsInline
                preload="auto"
                poster={homeProductPoster}
                onCanPlay={heroVideo.onVideoReady}
                onPlaying={heroVideo.onVideoReady}
                onError={() => {
                  heroVideo.onVideoError();
                  onProductVideoError?.();
                }}
              />
            ) : null}
          </div>
          <div className="home-product-hero__overlay" />
        </div>
        <div ref={heroVideo.contentRef} className="home-product-hero__content">
          <HeroTitle />
          <p className="home-product-hero__description" data-home-typography-region="heroBody">{labels.heroDescription}</p>
          <div className="home-product-hero__create-stage">
            {isInteractive && interactions ? (
              <button className="home-product-hero__create" type="button" onClick={interactions.createProject} data-home-typography-region="heroAction">
                <CreateProjectButtonContent label={labels.createProject} />
              </button>
            ) : (
              <span className="home-product-hero__create home-product-hero__create--static" data-home-typography-region="heroAction">
                <CreateProjectButtonContent label={labels.createProject} />
              </span>
            )}
          </div>
        </div>

        {heroVideo.videoEnabled ? (
          <button
            className="home-product-hero__mute"
            type="button"
            aria-label={heroVideo.muted ? labels.unmute : labels.mute}
            aria-pressed={!heroVideo.muted}
            onClick={heroVideo.toggleMuted}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M11 5 6 9H3v6h3l5 4V5Z" />
              {heroVideo.muted ? <path d="m16 9 6 6m0-6-6 6" /> : <path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14" />}
            </svg>
          </button>
        ) : null}
      </section>

      <div className="content-wrap">
        <section
          ref={recentReveal?.sectionRef}
          className="home-reveal-section home-reveal-section--recent"
          data-reveal-state={recentState}
          aria-label={labels.recentProjects}
        >
          <div data-reveal-item style={motionStyle("--home-reveal-delay", "0ms")}>
            <SectionTitle title={labels.recentProjects} />
          </div>
          {isInteractive ? recentContent : <StaticRecentCards />}
        </section>

        <section
          ref={discoverReveal?.sectionRef}
          className="home-reveal-section home-reveal-section--discover"
          data-reveal-state={discoverState}
          aria-label={labels.discover}
        >
          <div data-reveal-item style={motionStyle("--home-reveal-delay", "0ms")}>
            <SectionTitle title={labels.discover} />
          </div>
          {isInteractive && interactions ? <InteractiveDiscover openPreview={interactions.openPreview} /> : <StaticDiscover />}
        </section>
      </div>

      {isInteractive && interactions ? (
        <div className={`video-modal ${previewOpen ? "is-open" : ""}`}>
          <div className="modal-card">
            <div className="modal-preview"><span aria-hidden="true">▶</span></div>
            <div className="composer-footer" style={{ marginTop: 14 }}>
              <strong>{labels.previewCase}</strong>
              <button className="small-action" type="button" onClick={interactions.closePreview}>{labels.close}</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
