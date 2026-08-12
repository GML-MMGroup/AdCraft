import { useState, type CSSProperties } from "react";

export type DiscoverOrbitItem = {
  title: string;
  image: string;
};

type DiscoverOrbitProps = {
  items: readonly DiscoverOrbitItem[];
  interactive: boolean;
  onSelect?: () => void;
};

function orbitItemStyle(index: number, total: number): CSSProperties {
  return {
    "--discover-orbit-position": `${(index / total) * 100}%`,
    "--discover-orbit-float-delay": `${index * -530}ms`,
    "--home-reveal-delay": `${170 + index * 65}ms`,
  } as CSSProperties;
}

export function DiscoverOrbit({ items, interactive, onSelect }: DiscoverOrbitProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const isPaused = activeIndex !== null;

  const beginInteraction = (index: number) => {
    if (interactive) {
      setActiveIndex(index);
    }
  };

  const endInteraction = () => {
    if (interactive) {
      setActiveIndex(null);
    }
  };

  return (
    <div
      className={`discover-orbit ${interactive ? "" : "discover-orbit--static"}`}
      aria-label="Discover inspiration gallery"
      data-paused={isPaused}
      data-reveal-item
      style={{ "--home-reveal-delay": "170ms" } as CSSProperties}
    >
      <div className="discover-orbit__halo" aria-hidden="true" />
      <div className="discover-orbit__track">
        {items.map((item, index) => {
          const active = activeIndex === index;
          const sharedProps = {
            className: `discover-orbit__card ${active ? "is-active" : ""}`,
            style: orbitItemStyle(index, items.length),
          };

          return (
            <div className="discover-orbit__slot" key={item.title} style={orbitItemStyle(index, items.length)}>
              {interactive ? (
                <button
                  {...sharedProps}
                  type="button"
                  aria-label={item.title}
                  aria-pressed={active}
                  onPointerEnter={() => beginInteraction(index)}
                  onPointerLeave={endInteraction}
                  onMouseEnter={() => beginInteraction(index)}
                  onMouseLeave={endInteraction}
                  onFocus={() => beginInteraction(index)}
                  onBlur={endInteraction}
                  onClick={onSelect}
                >
                  <OrbitCardContent item={item} />
                </button>
              ) : (
                <article {...sharedProps} aria-label={item.title}>
                  <OrbitCardContent item={item} />
                </article>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function OrbitCardContent({ item }: { item: DiscoverOrbitItem }) {
  return (
    <span className="discover-orbit__card-frame">
      <img className="discover-orbit__image" src={item.image} alt="" loading="lazy" decoding="async" />
      <span className="discover-orbit__glass" aria-hidden="true" />
      <span className="discover-orbit__title" data-home-typography-region="cardTitle">{item.title}</span>
    </span>
  );
}
