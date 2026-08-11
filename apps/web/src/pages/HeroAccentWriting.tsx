import { useId, type CSSProperties } from "react";

type AccentStroke = {
  d: string;
  delay: string;
  duration: string;
};

const accentStrokes: readonly AccentStroke[] = [
  { d: "M16 116 C32 72 51 30 72 22 C82 52 92 87 105 116", delay: "0ms", duration: "520ms" },
  { d: "M38 84 C58 77 79 76 97 82", delay: "180ms", duration: "260ms" },
  { d: "M127 88 C116 70 122 54 139 56 C158 58 160 91 141 102 C124 112 112 97 125 82 C141 65 157 44 161 22", delay: "330ms", duration: "560ms" },
  { d: "M161 22 C166 51 163 89 159 104 C158 111 169 112 181 98", delay: "610ms", duration: "420ms" },
  { d: "M204 112 C202 81 207 43 225 35 C238 29 245 42 237 54", delay: "790ms", duration: "470ms" },
  { d: "M195 69 C210 65 229 64 243 67", delay: "970ms", duration: "260ms" },
  { d: "M253 75 C254 87 252 99 253 105 C254 112 264 112 273 99", delay: "1130ms", duration: "340ms" },
  { d: "M254 53 C254 52 255 51 256 51", delay: "1250ms", duration: "160ms" },
  { d: "M287 28 C280 48 279 76 280 100 C281 114 294 112 304 98", delay: "1380ms", duration: "470ms" },
  { d: "M312 105 C312 86 318 74 328 75 C341 76 337 101 337 105 C337 87 344 74 354 75 C367 77 364 101 365 105", delay: "1580ms", duration: "640ms" },
  { d: "M365 105 C368 111 378 109 388 97", delay: "1930ms", duration: "280ms" },
  { d: "M405 105 C405 103 407 102 409 104", delay: "2110ms", duration: "150ms" },
];

export function HeroAccentWriting() {
  const gradientId = `home-hero-accent-gold-${useId().replaceAll(":", "")}`;

  return (
    <svg
      className="home-hero-accent-writing"
      viewBox="0 0 425 140"
      role="img"
      aria-label="Ad film."
      focusable="false"
    >
      <title>Ad film.</title>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#b98028" />
          <stop offset="42%" stopColor="#ffe6a0" />
          <stop offset="67%" stopColor="#cf9839" />
          <stop offset="100%" stopColor="#8f5d16" />
        </linearGradient>
      </defs>
      {accentStrokes.map((stroke, index) => (
        <path
          key={stroke.d}
          className="home-hero-accent-writing__stroke"
          d={stroke.d}
          pathLength={1}
          style={{
            "--home-hero-accent-delay": stroke.delay,
            "--home-hero-accent-duration": stroke.duration,
          } as CSSProperties}
          stroke={`url(#${gradientId})`}
          strokeWidth={8}
          data-stroke-index={index}
        />
      ))}
    </svg>
  );
}
