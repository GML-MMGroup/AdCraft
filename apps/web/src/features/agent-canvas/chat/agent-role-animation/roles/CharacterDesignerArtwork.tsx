import React from "react";
import { CHARACTER_JACKET_OUTLINE, CHARACTER_PARK, CHARACTER_ROUTES } from "./characterDesignerGeometry.ts";

const MASK_STYLE = { transformBox: "view-box", transformOrigin: "0px 0px" } as const;

/** Canonical Idle geometry: runtime and exported static poster share this tree. */
export function CharacterDesignerArtwork({ idPrefix }: { idPrefix: string }) {
  const maskId = (id: string) => `${idPrefix}-character-${id}`;
  return (
    <React.Fragment>
      <defs>
        {CHARACTER_ROUTES.map((route) => (
          <mask key={route.id} id={maskId(route.id)} x="0" y="0" width="512" height="512" maskUnits="userSpaceOnUse">
            <rect data-part={`reveal-${route.id}`} data-motion-measurement="internal-clip"
              x={route.axis === 0 ? -512 : 0} y={route.axis === 1 ? -512 : 0} width="512" height="512"
              fill="white" opacity={route.phase === "construction" ? 1 : 0}
              style={{ ...MASK_STYLE, transform: `translate${route.axis === 0 ? "X" : "Y"}(${route.phase === "construction" ? 512 : 0}px)` }} />
          </mask>
        ))}
      </defs>

      <g data-part="base" strokeLinecap="round" strokeLinejoin="round">
        <path data-garment="outline" d={CHARACTER_JACKET_OUTLINE} fill="none" stroke="#FAFBFF" strokeWidth="8" />
        <path d="M201 302c0 10-3 21-7 28M273 257v70" fill="none" stroke="#FAFBFF" strokeWidth="8" />
        <path d="M194 337Q230 351 269 335" fill="none" stroke="#FAFBFF" strokeWidth="6" opacity="0.65" />
        <path d="M180 327 194 332 209 354M273 327 286 347" fill="none" stroke="#7899E2" strokeWidth="6" />
        <path d="M179 177C177 196 180 215 165 236 163 240 160 243 159 246 160 250 169 252 175 252 178 261 172 272 180 283 190 299 203 303 213 303 240 302 263 280 273 257l15-37-11-49-40-31-58 37Z"
          fill="#17202C" fillOpacity="0.65" />
        <path d="M153 142C159 111 182 88 219 98 254 108 299 99 309 133c15 21 6 44-10 58l-15 22-16-26c-20-10-25-32-22-48-21 20-51 35-75 34-17-1-25-22-18-31Z"
          fill="#17202C" fillOpacity="0.6" />
        <path d="M309 133c15 21 6 44-10 58l-15 22-16-26c-20-10-25-32-22-48-21 20-51 35-75 34-17-1-25-22-18-31"
          fill="none" stroke="#FAFBFF" strokeWidth="8" />
        <path d="M278 220c7-16 22-19 24-6 2 15-9 29-22 32" fill="#17202C" stroke="#FAFBFF" strokeWidth="7" />
        <path d="M190 199c9-6 20-6 28-3m-26 15c6-4 14-4 20-1m-33 56c8 3 16 1 22-3" fill="none" stroke="#FAFBFF" strokeWidth="6" />
        <circle cx="202" cy="212" r="2.5" fill="#FAFBFF" />
        <path d="M171 138c19-16 42-20 64-15" fill="none" stroke="#7899E2" strokeWidth="6" opacity="0.8" />
      </g>

      {(["hair", "face", "collar"] as const).map((region) => (
        <g key={region} data-design-region={region} fill="none" strokeLinecap="round" strokeLinejoin="round">
          {CHARACTER_ROUTES.filter((route) => route.region === region).map((route) => (
            <g key={route.id}>
              <path data-completed-stroke={route.phase === "refinement" ? route.id : undefined}
                d={route.path} stroke={route.color} strokeWidth={route.strokeWidth}
                opacity={route.phase === "construction" ? 0.35 : 0.8} />
              {route.phase === "construction" && <path data-completed-stroke={route.id} d={route.path}
                mask={`url(#${maskId(route.id)})`} stroke={route.color} strokeWidth={route.strokeWidth} />}
            </g>
          ))}
          {(["construction", "refinement"] as const).map((phase) => (
            <g key={phase} data-part={`ink-${phase}-${region}`} opacity="0">
              {CHARACTER_ROUTES.filter((route) => route.region === region && route.phase === phase).map((route) => (
                <path key={route.id} data-active-stroke={route.id} d={route.path}
                  stroke={route.color} strokeWidth={route.strokeWidth} mask={`url(#${maskId(route.id)})`} />
              ))}
            </g>
          ))}
        </g>
      ))}

      <g data-part="design-pencil" style={{ ...MASK_STYLE, transform: `translate(${CHARACTER_PARK.point[0]}px, ${CHARACTER_PARK.point[1]}px) rotate(0deg)` }}
        strokeLinecap="round" strokeLinejoin="round">
        <path d="m0 0 4-20 35-56c2-4 6-5 10-2l6 4c3 2 4 6 2 9L20-9 0 0Z"
          fill="#17202C" stroke="#FAFBFF" strokeWidth="6" />
        <path data-pencil-grip="" d="m4-20 12-19 16 10L20-9 4-20Z" fill="#FFB323" />
        <path d="m20-39 23-37 10 6-23 37" fill="#7899E2" fillOpacity="0.65" />
        <path d="m4-20 16 11L0 0 4-20Z" fill="#C8D8F7" stroke="#FAFBFF" strokeWidth="4" />
      </g>
    </React.Fragment>
  );
}
