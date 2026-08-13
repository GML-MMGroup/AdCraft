import { useId, type CSSProperties } from "react";
import { waterBrushAdFilmGlyphPaths } from "./heroWaterBrushGlyphPaths";

type WritingStroke = {
  d: string;
  delay: string;
  duration: string;
  width: number;
  glyphIndex: number;
};

// Water Brush has a 1000-unit em. At 80px, 0.100em tracking is 100 font units.
const waterBrushTrackingOffsets = [0, 100, 300, 400, 500, 600, 700] as const;

const glyphCoverageTimings = [
  { delay: "0ms", duration: "540ms" },
  { delay: "500ms", duration: "430ms" },
  { delay: "760ms", duration: "560ms" },
  { delay: "1280ms", duration: "260ms" },
  { delay: "1520ms", duration: "380ms" },
  { delay: "1710ms", duration: "510ms" },
  { delay: "2100ms", duration: "120ms" },
] as const;

// The primary paths establish the calligraphic order. The wider finishing passes
// remain moving pen strokes inside the real glyph outlines; they never reveal a full glyph at once.
const waterBrushStrokes: readonly WritingStroke[] = [
  { d: "M25 -105 C150 88 332 258 560 374", delay: "0ms", duration: "400ms", width: 94, glyphIndex: 0 },
  { d: "M278 246 C493 310 710 328 909 351", delay: "180ms", duration: "400ms", width: 92, glyphIndex: 0 },
  { d: "M668 354 C800 474 916 632 1017 768", delay: "340ms", duration: "200ms", width: 86, glyphIndex: 0 },
  { d: "M1184 88 C1334 27 1528 123 1588 283 C1641 423 1562 604 1425 629", delay: "500ms", duration: "430ms", width: 104, glyphIndex: 1 },
  { d: "M1951 -104 C2117 83 2300 264 2456 529", delay: "760ms", duration: "390ms", width: 92, glyphIndex: 2 },
  { d: "M2156 76 C2273 50 2393 63 2510 96", delay: "930ms", duration: "450ms", width: 74, glyphIndex: 2 },
  { d: "M2412 84 C2448 173 2484 270 2513 388", delay: "1130ms", duration: "190ms", width: 72, glyphIndex: 2 },
  { d: "M2518 603 C2523 621 2527 639 2532 655", delay: "1280ms", duration: "280ms", width: 82, glyphIndex: 3 },
  { d: "M2674 -6 C2765 171 2854 388 2975 744", delay: "1410ms", duration: "130ms", width: 78, glyphIndex: 3 },
  { d: "M3045 122 C3118 222 3153 341 3173 450", delay: "1520ms", duration: "380ms", width: 94, glyphIndex: 4 },
  { d: "M3174 451 C3268 299 3375 296 3423 451 C3463 309 3539 300 3590 410", delay: "1710ms", duration: "520ms", width: 96, glyphIndex: 5 },
  { d: "M3680 55 C3700 57 3721 60 3740 64", delay: "2100ms", duration: "120ms", width: 76, glyphIndex: 6 },

  { d: "M0 -112 C148 120 360 335 604 418", delay: "80ms", duration: "420ms", width: 238, glyphIndex: 0 },
  { d: "M185 308 C412 356 682 368 928 398", delay: "265ms", duration: "365ms", width: 202, glyphIndex: 0 },
  { d: "M612 372 C790 510 915 654 1030 790", delay: "410ms", duration: "270ms", width: 184, glyphIndex: 0 },
  { d: "M1140 86 C1324 -4 1566 108 1630 318 C1682 490 1572 658 1412 665", delay: "620ms", duration: "420ms", width: 220, glyphIndex: 1 },
  { d: "M1368 420 C1470 278 1570 84 1658 -12 C1710 -66 1755 -18 1728 94 C1666 310 1582 560 1500 688", delay: "770ms", duration: "380ms", width: 178, glyphIndex: 1 },
  { d: "M1920 -116 C2072 60 2296 284 2478 560", delay: "910ms", duration: "410ms", width: 216, glyphIndex: 2 },
  { d: "M2106 66 C2250 28 2420 50 2538 112", delay: "1080ms", duration: "350ms", width: 170, glyphIndex: 2 },
  { d: "M2382 88 C2434 214 2488 382 2528 504", delay: "1240ms", duration: "250ms", width: 150, glyphIndex: 2 },
  { d: "M2502 550 C2554 578 2602 620 2642 660", delay: "1340ms", duration: "230ms", width: 172, glyphIndex: 3 },
  { d: "M2650 -20 C2744 164 2864 456 2988 768", delay: "1470ms", duration: "250ms", width: 164, glyphIndex: 3 },
  { d: "M3018 90 C3124 242 3172 374 3196 500", delay: "1560ms", duration: "360ms", width: 202, glyphIndex: 4 },
  { d: "M3150 454 C3262 252 3390 264 3442 462", delay: "1780ms", duration: "350ms", width: 202, glyphIndex: 5 },
  { d: "M3432 448 C3534 252 3630 298 3676 450", delay: "1900ms", duration: "260ms", width: 178, glyphIndex: 5 },
  { d: "M3562 406 C3652 470 3730 450 3800 390", delay: "1995ms", duration: "170ms", width: 150, glyphIndex: 5 },
  { d: "M3420 468 C3516 590 3635 600 3740 510", delay: "2050ms", duration: "130ms", width: 138, glyphIndex: 5 },
  { d: "M3662 30 C3712 34 3760 50 3794 84", delay: "2110ms", duration: "110ms", width: 158, glyphIndex: 6 },
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
      data-writing-duration="2220ms"
      focusable="false"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#b98028" />
          <stop offset="42%" stopColor="#ffe6a0" />
          <stop offset="67%" stopColor="#cf9839" />
          <stop offset="100%" stopColor="#8f5d16" />
        </linearGradient>
        <mask
          id={maskId}
          maskUnits="userSpaceOnUse"
          x="-256"
          y="-256"
          width="4400"
          height="1500"
        >
          <rect x="-256" y="-256" width="4400" height="1500" fill="#000" />
          <g data-writing-mask-space="glyph-space" transform={waterBrushTransform}>
            {waterBrushStrokes.map((stroke, index) => (
              <path
                key={`${stroke.glyphIndex}-${index}`}
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
                data-writing-stroke={index + 1}
                data-writing-glyph={stroke.glyphIndex + 1}
              />
            ))}
            {waterBrushAdFilmGlyphPaths.map((glyph, index) => {
              const timing = glyphCoverageTimings[index]!;

              return (
                <path
                  key={glyph.character}
                  className="home-hero-accent-writing__coverage"
                  d={glyph.d}
                  transform={`translate(${waterBrushTrackingOffsets[index]!} 0) ${glyph.transform}`}
                  pathLength={1}
                  fill="none"
                  stroke="#fff"
                  strokeWidth={320}
                  style={
                    {
                      "--home-hero-accent-delay": timing.delay,
                      "--home-hero-accent-duration": timing.duration,
                    } as CSSProperties
                  }
                  data-writing-coverage={index + 1}
                />
              );
            })}
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
