import { useId, type CSSProperties } from "react";

type AccentStroke = {
  d: string;
  delay: string;
  duration: string;
  width: number;
};

const accentStrokes: readonly AccentStroke[] = [
  { d: "M53 112 C66 78 81 39 94 20", delay: "0ms", duration: "400ms", width: 28 },
  { d: "M94 20 C103 50 111 80 120 112", delay: "180ms", duration: "400ms", width: 28 },
  { d: "M68 79 C84 75 101 75 113 79", delay: "340ms", duration: "200ms", width: 21 },
  { d: "M148 79 C129 66 130 96 144 103 C161 111 173 91 159 79 C146 67 128 79 142 93", delay: "500ms", duration: "430ms", width: 29 },
  { d: "M163 28 C164 56 160 84 159 103 C158 111 170 111 181 99", delay: "760ms", duration: "390ms", width: 25 },
  { d: "M207 112 C206 76 214 42 233 32 C246 25 254 35 246 48", delay: "930ms", duration: "450ms", width: 26 },
  { d: "M196 67 C214 64 235 64 251 68", delay: "1130ms", duration: "190ms", width: 20 },
  { d: "M267 76 C267 89 266 100 268 105 C271 112 281 110 290 99", delay: "1280ms", duration: "280ms", width: 24 },
  { d: "M270 54 C270 53 271 52 272 52", delay: "1410ms", duration: "130ms", width: 24 },
  { d: "M306 29 C297 52 298 83 300 102 C302 114 315 111 325 99", delay: "1520ms", duration: "380ms", width: 26 },
  { d: "M337 105 C337 86 344 74 355 75 C368 76 366 100 367 105 C367 87 375 74 387 75 C401 77 398 101 400 105 C402 112 412 109 423 98", delay: "1710ms", duration: "520ms", width: 27 },
  { d: "M444 105 C444 103 446 102 448 104", delay: "2100ms", duration: "120ms", width: 24 },
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
