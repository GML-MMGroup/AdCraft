import { useId, type CSSProperties } from "react";

type AccentStroke = {
  d: string;
  delay: string;
  duration: string;
  width: number;
};

const accentStrokes: readonly AccentStroke[] = [
  { d: "M43 112 C50 85 60 45 69 18", delay: "0ms", duration: "400ms", width: 29 },
  { d: "M69 18 C77 45 82 80 89 112", delay: "180ms", duration: "400ms", width: 29 },
  { d: "M52 79 C64 75 77 75 86 79", delay: "340ms", duration: "200ms", width: 21 },
  { d: "M126 79 C111 65 92 76 98 94 C104 111 128 105 132 89 C134 79 126 73 117 76", delay: "500ms", duration: "430ms", width: 31 },
  { d: "M134 17 C133 48 131 82 132 103 C133 112 143 111 153 99", delay: "760ms", duration: "390ms", width: 26 },
  { d: "M181 112 C176 85 181 47 193 22 C198 11 207 12 207 23", delay: "930ms", duration: "450ms", width: 26 },
  { d: "M164 68 C175 64 189 64 199 67", delay: "1130ms", duration: "190ms", width: 20 },
  { d: "M207 76 C206 89 207 101 209 105 C212 112 220 110 227 99", delay: "1280ms", duration: "280ms", width: 23 },
  { d: "M209 52 C209 51 210 50 211 50", delay: "1410ms", duration: "130ms", width: 19 },
  { d: "M241 18 C233 51 234 85 236 103 C238 113 247 111 255 99", delay: "1520ms", duration: "380ms", width: 25 },
  { d: "M267 105 C267 86 274 74 284 75 C297 76 295 100 296 105 C296 87 304 74 315 75 C329 77 327 101 329 105 C331 112 339 109 347 98", delay: "1710ms", duration: "520ms", width: 28 },
  { d: "M354 104 C354 102 356 101 358 103", delay: "2100ms", duration: "120ms", width: 20 },
];

export function HeroAccentWriting() {
  const gradientId = `home-hero-accent-gold-${useId().replaceAll(":", "")}`;
  const maskId = `home-hero-accent-writing-mask-${useId().replaceAll(":", "")}`;

  return (
    <svg
      className="home-hero-accent-writing"
      viewBox="0 0 480 140"
      role="img"
      aria-label="Ad film."
      focusable="false"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#b98028" />
          <stop offset="42%" stopColor="#ffe6a0" />
          <stop offset="67%" stopColor="#cf9839" />
          <stop offset="100%" stopColor="#8f5d16" />
        </linearGradient>
        <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="480" height="140">
          <rect width="480" height="140" fill="#000" />
          {accentStrokes.map((stroke, index) => (
            <path
              key={stroke.d}
              className="home-hero-accent-writing__stroke"
              d={stroke.d}
              pathLength={1}
              stroke="#fff"
              strokeWidth={stroke.width}
              style={{
                "--home-hero-accent-delay": stroke.delay,
                "--home-hero-accent-duration": stroke.duration,
              } as CSSProperties}
              data-stroke-index={index}
            />
          ))}
          <rect
            className="home-hero-accent-writing__completion"
            width="480"
            height="140"
            fill="#fff"
          />
        </mask>
      </defs>
      <text
        className="home-hero-accent-writing__glyph"
        x="37"
        y="112"
        fontFamily={'Georgia, "Instrument Serif", serif'}
        fontSize="108"
        fontStyle="italic"
        fontWeight="400"
        letterSpacing="3"
        fill={`url(#${gradientId})`}
        mask={`url(#${maskId})`}
      >
        Ad film.
      </text>
    </svg>
  );
}
