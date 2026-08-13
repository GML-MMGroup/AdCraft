import { useId, type CSSProperties } from "react";
import { waterBrushAdFilmGlyphPaths } from "./heroWaterBrushGlyphPaths";

type WritingStroke = {
  d: string;
  delay: string;
  duration: string;
  width: number;
  glyphIndex: number;
};

const glyphCompletionDelays = [
  "540ms",
  "930ms",
  "1320ms",
  "1540ms",
  "1900ms",
  "2230ms",
  "2220ms",
] as const;

// Water Brush has a 1000-unit em. At 80px, 0.100em tracking is 100 font units.
// The source font already places the word space; tracking is also applied on either side of it.
const waterBrushTrackingOffsets = [0, 100, 300, 400, 500, 600, 700] as const;

// These authored trajectories are the visual pen strokes for Water Brush.
// Each path is clipped to its glyph and accumulates in the SVG mask as it is written.
const waterBrushStrokes: readonly WritingStroke[] = [
  {
    d: "M25 -105 C150 88 332 258 560 374",
    delay: "0ms",
    duration: "400ms",
    width: 94,
    glyphIndex: 0,
  },
  {
    d: "M278 246 C493 310 710 328 909 351",
    delay: "180ms",
    duration: "400ms",
    width: 92,
    glyphIndex: 0,
  },
  {
    d: "M668 354 C800 474 916 632 1017 768",
    delay: "340ms",
    duration: "200ms",
    width: 86,
    glyphIndex: 0,
  },
  {
    d: "M1184 88 C1334 27 1528 123 1588 283 C1641 423 1562 604 1425 629",
    delay: "500ms",
    duration: "430ms",
    width: 104,
    glyphIndex: 1,
  },
  {
    d: "M1951 -104 C2117 83 2300 264 2456 529",
    delay: "760ms",
    duration: "390ms",
    width: 92,
    glyphIndex: 2,
  },
  {
    d: "M2156 76 C2273 50 2393 63 2510 96",
    delay: "930ms",
    duration: "450ms",
    width: 74,
    glyphIndex: 2,
  },
  {
    d: "M2412 84 C2448 173 2484 270 2513 388",
    delay: "1130ms",
    duration: "190ms",
    width: 72,
    glyphIndex: 2,
  },
  {
    d: "M2518 603 C2523 621 2527 639 2532 655",
    delay: "1280ms",
    duration: "280ms",
    width: 82,
    glyphIndex: 3,
  },
  {
    d: "M2674 -6 C2765 171 2854 388 2975 744",
    delay: "1410ms",
    duration: "130ms",
    width: 78,
    glyphIndex: 3,
  },
  {
    d: "M3045 122 C3118 222 3153 341 3173 450",
    delay: "1520ms",
    duration: "380ms",
    width: 94,
    glyphIndex: 4,
  },
  {
    d: "M3174 451 C3268 299 3375 296 3423 451 C3463 309 3539 300 3590 410",
    delay: "1710ms",
    duration: "520ms",
    width: 96,
    glyphIndex: 5,
  },
  {
    d: "M3680 55 C3700 57 3721 60 3740 64",
    delay: "2100ms",
    duration: "120ms",
    width: 76,
    glyphIndex: 6,
  },
];

const waterBrushTransform = "translate(4 822) scale(1 -1)";

export function HeroAccentWriting() {
  const gradientId = `home-hero-accent-gold-${useId().replaceAll(":", "")}`;
  const maskId = `home-hero-accent-writing-mask-${useId().replaceAll(":", "")}`;

  return (
    <svg
      className="home-hero-accent-writing"
      viewBox="-40 -40 3880 1100"
      role="img"
      aria-label="Ad film."
      data-writing-font="Water Brush"
      data-writing-tracking="0.100em"
      focusable="false"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#b98028" />
          <stop offset="42%" stopColor="#ffe6a0" />
          <stop offset="67%" stopColor="#cf9839" />
          <stop offset="100%" stopColor="#8f5d16" />
        </linearGradient>
        {waterBrushAdFilmGlyphPaths.map((glyph, index) => (
          <clipPath
            key={glyph.character}
            id={`${maskId}-glyph-${index}`}
            clipPathUnits="userSpaceOnUse"
          >
            <path
              d={glyph.d}
              transform={`translate(${waterBrushTrackingOffsets[index]!} 0) ${glyph.transform}`}
            />
          </clipPath>
        ))}
        <mask
          id={maskId}
          maskUnits="userSpaceOnUse"
          x="-40"
          y="-40"
          width="3880"
          height="1100"
        >
          <rect x="-40" y="-40" width="3880" height="1100" fill="#000" />
          <g>
            {waterBrushStrokes.map((stroke, index) => (
              <g
                key={stroke.d}
                clipPath={`url(#${maskId}-glyph-${stroke.glyphIndex})`}
              >
                  <path
                    className="home-hero-accent-writing__stroke"
                    d={stroke.d}
                    pathLength={1}
                    fill="none"
                    stroke="#fff"
                    strokeWidth={stroke.width}
                    style={
                      {
                        "--home-hero-accent-delay": stroke.delay,
                        "--home-hero-accent-duration": stroke.duration,
                      } as CSSProperties
                    }
                    data-stroke-index={index}
                  />
              </g>
            ))}
            {waterBrushAdFilmGlyphPaths.map((glyph, index) => (
              <path
                key={glyph.character}
                className="home-hero-accent-writing__completion-glyph"
                d={glyph.d}
                transform={`translate(${waterBrushTrackingOffsets[index]!} 0) ${glyph.transform}`}
                fill="#fff"
                style={
                  {
                    "--home-hero-accent-completion-delay": glyphCompletionDelays[index]!,
                  } as CSSProperties
                }
              />
            ))}
          </g>
        </mask>
      </defs>
      <g fill={`url(#${gradientId})`} mask={`url(#${maskId})`} transform={waterBrushTransform}>
        {waterBrushAdFilmGlyphPaths.map((glyph, index) => (
          <path
            key={glyph.character}
            className="home-hero-accent-writing__glyph-path"
            d={glyph.d}
            transform={`translate(${waterBrushTrackingOffsets[index]!} 0) ${glyph.transform}`}
          />
        ))}
      </g>
    </svg>
  );
}
