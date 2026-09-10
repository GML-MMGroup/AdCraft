const SCAN_STYLE = { transformBox: "view-box", transformOrigin: "center" } as const;

/** Hook-free canonical scene tree shared by runtime and static poster rendering. */
export function SceneDesignerArtwork({ idPrefix }: { idPrefix: string }) {
  const revealMaskId = `${idPrefix}-scene-reveal`;
  const constructionMaskId = `${idPrefix}-construction-hide`;
  const revealFeatherId = `${idPrefix}-scene-reveal-feather`;
  const constructionFeatherId = `${idPrefix}-construction-feather`;
  const scanGradientId = `${idPrefix}-scene-scan-gradient`;
  const sceneClipId = `${idPrefix}-scene-clip`;
  const lineworkId = `${idPrefix}-scene-linework`;
  const sunId = `${idPrefix}-scene-sun`;

  return (
    <>
      <defs>
        <g id={lineworkId} fill="none" strokeLinecap="round" strokeLinejoin="round">
          <g data-scene-reference="atlas-row-2-col-1" transform="translate(72 60) scale(1.3)">
            <g data-scene-element="floor-grid" stroke="#88ABFF" strokeWidth="3.2">
              <line data-scene-line="grid-depth" x1="103" y1="181" x2="22" y2="252" />
              <line data-scene-line="grid-depth" x1="119" y1="181" x2="63" y2="276" />
              <line data-scene-line="grid-depth" x1="138" y1="181" x2="138" y2="276" />
              <line data-scene-line="grid-depth" x1="152" y1="181" x2="217" y2="276" />
              <line data-scene-line="grid-depth" x1="166" y1="181" x2="260" y2="252" />
              <line data-scene-line="grid-cross" x1="80" y1="192" x2="194" y2="192" />
              <line data-scene-line="grid-cross" x1="55" y1="207" x2="216" y2="207" />
              <line data-scene-line="grid-cross" x1="38" y1="227" x2="251" y2="227" />
              <line data-scene-line="grid-cross" x1="22" y1="252" x2="260" y2="252" />
            </g>
            <g data-scene-element="back-wall" stroke="#88ABFF" strokeWidth="3.2">
              <path d="M94 115H173M118 116v55M138 130v38M155 120v48M119 141h13M119 156h14M138 147h33" />
              <path d="M92 181h86" stroke="#F8FAFF" strokeWidth="3.8" />
            </g>
            <g data-scene-element="left-wall">
              <path d="M33 210V41l60 57v83L22 228" stroke="#F8FAFF" strokeWidth="3.8" />
              <path d="M35 89l38 23v82" stroke="#F8FAFF" strokeWidth="3.5" />
              <path d="M35 89l20 12M35 128l22 8v58" stroke="#88ABFF" strokeWidth="3.2" />
            </g>
            <g data-scene-element="right-wall">
              <path d="M178 181V97l75-56v186M178 181l84 51" stroke="#F8FAFF" strokeWidth="3.8" />
              <path d="M253 89v114M256 229l6 3" stroke="#88ABFF" strokeWidth="3.2" />
            </g>
            <g data-scene-element="arch" strokeWidth="3.5">
              <path d="M208 190v-61c0-13 6-24 16-29M198 127h10M208 190h28" stroke="#88ABFF" />
              <path d="M196 191v-61c0-16 10-30 22-30s19 10 19 25v91M209 172h27M198 189h38" stroke="#F8FAFF" />
            </g>
          </g>
        </g>
        <g id={sunId} data-scene-element="sun" fill="none" stroke="#FFCA62" strokeWidth="3.5">
          <circle data-scene-line="sun-core" cx="115" cy="54" r="16" />
          <path data-scene-line="sun-ray" d="M115 20v10" />
          <path data-scene-line="sun-ray" d="m92 29 7 7" />
          <path data-scene-line="sun-ray" d="M82 54h10" />
          <path data-scene-line="sun-ray" d="m92 78 7-7" />
          <path data-scene-line="sun-ray" d="M115 78v10" />
          <path data-scene-line="sun-ray" d="m132 71 7 7" />
          <path data-scene-line="sun-ray" d="M138 54h11" />
          <path data-scene-line="sun-ray" d="m132 36 7-7" />
        </g>
        <linearGradient id={revealFeatherId} gradientUnits="userSpaceOnUse" x1="0" y1="70" x2="0" y2="94">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="0.5" stopColor="#FFFFFF" />
          <stop offset="1" stopColor="#000000" />
        </linearGradient>
        <linearGradient id={constructionFeatherId} gradientUnits="userSpaceOnUse" x1="0" y1="70" x2="0" y2="94">
          <stop offset="0" stopColor="#000000" />
          <stop offset="0.5" stopColor="#000000" />
          <stop offset="1" stopColor="#FFFFFF" />
        </linearGradient>
        <linearGradient id={scanGradientId} gradientUnits="userSpaceOnUse" x1="86" y1="0" x2="430" y2="0">
          <stop offset="0" stopColor="#DDE9FF" stopOpacity="0" />
          <stop offset="0.12" stopColor="#BBD1FF" stopOpacity="0.76" />
          <stop offset="0.5" stopColor="#FFFFFF" />
          <stop offset="0.88" stopColor="#BBD1FF" stopOpacity="0.76" />
          <stop offset="1" stopColor="#DDE9FF" stopOpacity="0" />
        </linearGradient>
        <clipPath id={sceneClipId} clipPathUnits="userSpaceOnUse">
          <path transform="translate(72 60) scale(1.3)"
            d="M18 257V226l11-8V36l68 60v15h77V95l83-59v190l9 4v27h-58l13 24h-11l-17-24h-50v24h-10v-24H82l-16 24H57l14-24Z" />
          <path transform="translate(72 60) scale(1.3)" d="M78 15h76v79H78Z" />
        </clipPath>
        <mask id={revealMaskId} x="0" y="0" width="512" height="512" maskUnits="userSpaceOnUse">
          <rect width="512" height="512" fill="#000000" />
          <g data-part="scene-reveal" data-motion-measurement="internal-clip"
            transform="translate(0 392)" style={SCAN_STYLE}>
            <rect x="0" y="-512" width="512" height="594" fill="#FFFFFF" />
            <rect x="0" y="70" width="512" height="24" fill={`url(#${revealFeatherId})`} />
          </g>
        </mask>
        <mask id={constructionMaskId} x="0" y="0" width="512" height="512" maskUnits="userSpaceOnUse">
          <rect width="512" height="512" fill="#FFFFFF" />
          <g data-part="construction-hide" data-motion-measurement="internal-clip"
            transform="translate(0 392)" style={SCAN_STYLE}>
            <rect x="0" y="-512" width="512" height="594" fill="#000000" />
            <rect x="0" y="70" width="512" height="24" fill={`url(#${constructionFeatherId})`} />
          </g>
        </mask>
      </defs>

      <g data-part="construction-scene" mask={`url(#${constructionMaskId})`} opacity="0.24">
        <use href={`#${lineworkId}`} />
        <use href={`#${sunId}`} transform="translate(72 60) scale(1.3)" />
      </g>
      <g data-part="completed-scene" mask={`url(#${revealMaskId})`} fill="none">
        <use href={`#${lineworkId}`} />
        <g transform="translate(72 60) scale(1.3)">
          <g data-part="scene-accent" fill="none">
            <use href={`#${sunId}`} />
          </g>
        </g>
      </g>
      <g data-scene-scan-window="true" clipPath={`url(#${sceneClipId})`}>
        <g data-part="scene-scan" opacity={0} style={SCAN_STYLE}>
          <line x1="86" y1="82" x2="430" y2="82" stroke={`url(#${scanGradientId})`}
            strokeLinecap="round" strokeWidth="4" />
        </g>
      </g>
    </>
  );
}
