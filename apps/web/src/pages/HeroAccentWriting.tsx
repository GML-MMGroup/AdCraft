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

type AccentGlyphPath = {
  d: string;
  transform: string;
};

type AccentGlyphCoverage = AccentGlyphPath & {
  delay: string;
  duration: string;
};

// These outlines are exported from the bundled Instrument Serif Italic face.
// Keeping them in SVG makes the writing mask deterministic across devices.
const accentGlyphPaths: readonly AccentGlyphPath[] = [
  {
    d: "M-62 0Q-74 0 -74 10Q-74 19 -58 23L-42 26Q-22 30 -7.5 45.5Q7 61 20 89L319 714Q324 724 329 727Q334 730 338 730Q343 730 346.5 727Q350 724 350 714L361 80Q362 52 368 41.5Q374 31 393 26L406 23Q418 20 418 11Q418 0 401 0H236Q223 0 223 10Q223 21 243 23L263 25Q280 27 286.5 36Q293 45 293 67L291 222Q291 248 264 248H157Q131 248 118 222L53 88Q26 31 71 25L85 23Q100 21 100 11Q100 0 83 0ZM161 278H273Q290 278 290 295L288 568H283L152 295Q148 288 151 283Q154 278 161 278Z",
    transform: "translate(0 0)",
  },
  {
    d: "M90 -9Q53 -9 33 22Q13 53 13 113Q13 170 29 227.5Q45 285 73 337Q101 389 136.5 429Q172 469 211.5 492.5Q251 516 290 516Q317 516 337 502Q351 493 354 508L386 640Q391 658 386.5 665Q382 672 368 673L338 676Q323 677 325 689Q327 698 339 700Q375 706 403 714.5Q431 723 448 737Q456 743 463 743Q475 743 472 728L330 113Q315 48 350 48Q373 48 391.5 79Q410 110 429 175Q432 186 442 186Q449 186 451 180Q453 174 451 166Q432 72 398.5 31.5Q365 -9 320 -9Q281 -9 264.5 24Q248 57 261 114L272 160Q274 167 269.5 168Q265 169 262 163Q214 69 171 30Q128 -9 90 -9ZM114 42Q138 42 167 71Q196 100 224.5 146Q253 192 277 245Q301 298 315.5 347Q330 396 330 430Q330 491 287 491Q261 491 232 467.5Q203 444 176.5 404Q150 364 128.5 313.5Q107 263 94 208.5Q81 154 81 102Q81 67 90.5 54.5Q100 42 114 42Z",
    transform: "translate(485 0)",
  },
  {
    d: "M32 0Q19 0 22 13L123 445Q132 482 99 482H78Q62 482 62 496Q62 510 80 510Q111 510 126.5 518Q142 526 147 550Q160 607 185.5 651.5Q211 696 247 722Q283 748 326 748Q361 748 382.5 731.5Q404 715 404 686Q404 664 392.5 650.5Q381 637 364 637Q343 637 336.5 649Q330 661 328.5 677Q327 693 322 705Q317 717 299 717Q276 717 258.5 694.5Q241 672 227 610L207 523Q204 510 218 510H298Q317 510 313 496Q310 482 295 482H208Q198 482 195 472L88 11Q85 0 74 0Z",
    transform: "translate(1185 0)",
  },
  {
    d: "M204 605Q185 605 172.5 618.5Q160 632 160 651Q160 678 176.5 694Q193 710 214 710Q234 710 247.5 697.5Q261 685 261 665Q261 637 244 621Q227 605 204 605ZM122 -10Q89 -10 75 14.5Q61 39 74 95L148 412Q153 434 149.5 446.5Q146 459 131 459Q113 459 91.5 432.5Q70 406 43 332Q39 319 29 319Q14 319 21 337Q43 406 67.5 445Q92 484 117 500Q142 516 163 516Q198 516 212 491.5Q226 467 213 411L139 94Q134 72 137.5 59.5Q141 47 156 47Q174 47 195.5 73.5Q217 100 244 174Q248 187 258 187Q273 187 266 169Q245 101 219.5 61.5Q194 22 169 6Q144 -10 122 -10Z",
    transform: "translate(1486 0)",
  },
  {
    d: "M74 -10Q41 -10 27 14.5Q13 39 26 95L153 640Q158 658 153.5 665Q149 672 135 673L105 676Q90 677 92 689Q94 698 106 700Q142 706 170 714.5Q198 723 215 737Q223 743 230 743Q242 743 239 728L91 94Q86 72 89.5 59.5Q93 47 108 47Q126 47 147.5 73.5Q169 100 196 174Q200 187 210 187Q225 187 218 169Q197 101 171.5 61.5Q146 22 121 6Q96 -10 74 -10Z",
    transform: "translate(1802 0)",
  },
  {
    d: "M591 -9Q555 -9 537 21Q519 51 535 114L612 404Q623 443 615.5 458Q608 473 594 473Q574 473 548 445.5Q522 418 493.5 371Q465 324 438 264Q411 204 388 139Q365 74 350 11Q347 0 336 0H297Q283 0 286 13L378 404Q387 443 380.5 458Q374 473 360 473Q341 473 315 445.5Q289 418 261 371Q233 324 206 264Q179 204 156 139Q133 74 119 11Q116 0 105 0H64Q50 0 53 13L148 412Q153 434 149.5 446.5Q146 459 131 459Q113 459 91.5 432.5Q70 406 43 332Q39 319 29 319Q14 319 21 337Q43 406 67.5 445Q92 484 117 500Q142 516 163 516Q196 516 210 491.5Q224 467 211 411L186 303Q185 296 189 295Q193 294 196 300Q254 420 301 468Q348 516 387 516Q424 516 439.5 486Q455 456 441 394L420 303Q419 296 423 295Q427 294 430 300Q468 381 501.5 428.5Q535 476 565 496Q595 516 621 516Q658 516 675 486Q692 456 675 394L599 104Q592 76 598 62Q604 48 620 48Q640 48 659.5 74.5Q679 101 700 175Q703 186 713 186Q721 186 722.5 180Q724 174 722 166Q703 98 681 59.5Q659 21 636.5 6Q614 -9 591 -9Z",
    transform: "translate(2070 0)",
  },
  {
    d: "M62 -9Q41 -9 28 4.5Q15 18 15 38Q15 64 33 80Q51 96 71 96Q91 96 104.5 82.5Q118 69 118 49Q118 23 100 7Q82 -9 62 -9Z",
    transform: "translate(2843 0)",
  },
];

const accentGlyphCoverage: readonly AccentGlyphCoverage[] = [
  { ...accentGlyphPaths[0]!, delay: "0ms", duration: "540ms" },
  { ...accentGlyphPaths[1]!, delay: "500ms", duration: "430ms" },
  { ...accentGlyphPaths[2]!, delay: "760ms", duration: "560ms" },
  { ...accentGlyphPaths[3]!, delay: "1280ms", duration: "260ms" },
  { ...accentGlyphPaths[4]!, delay: "1520ms", duration: "380ms" },
  { ...accentGlyphPaths[5]!, delay: "1710ms", duration: "520ms" },
  { ...accentGlyphPaths[6]!, delay: "2100ms", duration: "120ms" },
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
          <g transform="translate(37 112) scale(0.108 -0.108)">
            {accentGlyphCoverage.map((glyph) => (
              <path
                key={glyph.transform}
                className="home-hero-accent-writing__coverage"
                d={glyph.d}
                transform={glyph.transform}
                pathLength={1}
                fill="none"
                stroke="#fff"
                strokeWidth={100}
                style={{
                  "--home-hero-accent-delay": glyph.delay,
                  "--home-hero-accent-duration": glyph.duration,
                } as CSSProperties}
              />
            ))}
          </g>
        </mask>
      </defs>
      <g fill={`url(#${gradientId})`} mask={`url(#${maskId})`}>
        <g transform="translate(37 112) scale(0.108 -0.108)">
          {accentGlyphPaths.map((glyph) => (
            <path
              key={glyph.transform}
              className="home-hero-accent-writing__glyph-path"
              d={glyph.d}
              transform={glyph.transform}
            />
          ))}
        </g>
      </g>
    </svg>
  );
}
