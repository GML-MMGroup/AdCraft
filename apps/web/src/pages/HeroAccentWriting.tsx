import { useId, type CSSProperties } from "react";

type BrushStroke = {
  d: string;
  delay: string;
  duration: string;
  width: number;
};

// These are the final visible strokes, not mask trajectories for a font outline.
// Each curve remains on-screen after drawing, so the word resolves naturally as a pen would write it.
const waterBrushStrokes: readonly BrushStroke[] = [
  { d: "M72 770 C168 618 292 296 426 8 C456 -54 526 -50 534 24 C547 153 469 380 365 606 C325 693 277 754 238 790", delay: "0ms", duration: "300ms", width: 92 },
  { d: "M162 534 C327 486 506 490 684 548", delay: "190ms", duration: "210ms", width: 72 },
  { d: "M364 607 C542 678 758 664 972 510", delay: "310ms", duration: "190ms", width: 78 },
  { d: "M1095 506 C1082 376 1184 298 1313 321 C1439 343 1466 461 1392 558 C1314 662 1155 644 1098 548 C1090 534 1088 520 1095 506", delay: "450ms", duration: "285ms", width: 92 },
  { d: "M1344 485 C1441 332 1549 103 1662 -8 C1715 -59 1767 -15 1734 88 C1662 308 1580 528 1521 653 C1491 717 1535 744 1627 690", delay: "640ms", duration: "285ms", width: 78 },
  { d: "M1874 658 C1938 462 2018 198 2080 36 C2108 -40 2207 -64 2260 10 C2295 61 2280 127 2254 180", delay: "820ms", duration: "280ms", width: 82 },
  { d: "M1925 416 C2048 383 2167 378 2292 406", delay: "970ms", duration: "150ms", width: 64 },
  { d: "M2052 236 C2166 210 2305 220 2402 265", delay: "1050ms", duration: "150ms", width: 58 },
  { d: "M2440 472 C2470 394 2533 379 2585 421 C2633 462 2598 570 2558 627 C2530 668 2580 692 2650 637", delay: "1170ms", duration: "205ms", width: 76 },
  { d: "M2542 254 C2562 226 2594 221 2614 244", delay: "1290ms", duration: "88ms", width: 68 },
  { d: "M2730 624 C2793 438 2865 164 2958 20 C2990 -28 3040 -14 3034 46 C3022 174 2926 382 2865 512 C2825 599 2851 670 2948 630", delay: "1410ms", duration: "220ms", width: 75 },
  { d: "M2896 517 C2980 558 3047 550 3106 500", delay: "1545ms", duration: "120ms", width: 58 },
  { d: "M3078 608 C3120 504 3170 422 3232 423 C3293 424 3286 539 3252 604", delay: "1640ms", duration: "190ms", width: 76 },
  { d: "M3250 602 C3293 497 3347 419 3403 426 C3457 433 3452 536 3420 600", delay: "1760ms", duration: "170ms", width: 76 },
  { d: "M3417 598 C3468 505 3516 452 3572 463 C3622 473 3630 555 3598 612", delay: "1870ms", duration: "162ms", width: 74 },
  { d: "M3596 610 C3650 570 3698 552 3758 575", delay: "1965ms", duration: "125ms", width: 58 },
  { d: "M3650 604 C3708 638 3760 644 3820 609", delay: "2032ms", duration: "110ms", width: 48 },
  { d: "M3862 613 C3884 600 3908 610 3910 633 C3908 656 3882 667 3864 650 C3852 639 3852 622 3862 613", delay: "2140ms", duration: "80ms", width: 70 },
];

export function HeroAccentWriting() {
  const gradientId = `home-hero-accent-gold-${useId().replaceAll(":", "")}`;

  return (
    <svg
      className="home-hero-accent-writing"
      viewBox="-120 -140 4140 1040"
      role="img"
      aria-label="Ad film."
      data-writing-font="Water Brush"
      data-writing-tracking="0.100em"
      data-writing-duration="2220ms"
      focusable="false"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#a66e22" />
          <stop offset="38%" stopColor="#ffe5a0" />
          <stop offset="66%" stopColor="#d39938" />
          <stop offset="100%" stopColor="#8f5d16" />
        </linearGradient>
      </defs>
      <g fill="none" stroke={`url(#${gradientId})`}>
        {waterBrushStrokes.map((stroke, index) => (
          <path
            key={stroke.d}
            className="home-hero-accent-writing__stroke"
            d={stroke.d}
            pathLength={1}
            strokeWidth={stroke.width}
            style={
              {
                "--home-hero-accent-delay": stroke.delay,
                "--home-hero-accent-duration": stroke.duration,
              } as CSSProperties
            }
            data-writing-stroke={index + 1}
          />
        ))}
      </g>
    </svg>
  );
}
