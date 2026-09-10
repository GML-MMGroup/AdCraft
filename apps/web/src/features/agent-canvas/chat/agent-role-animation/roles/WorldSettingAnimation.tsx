import { useId, useRef } from "react";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionState,
} from "../types.ts";
import { useAgentRoleMotion } from "../useAgentRoleMotion.ts";

const MOVING_PART_STYLE = {
  transformBox: "view-box",
  transformOrigin: "center",
} as const;
const ACCENT_STAR_STYLE = {
  opacity: 0.84,
  transform: "scale(1)",
  transformBox: "fill-box",
  transformOrigin: "center",
} as const;
const INTERVAL_EASING = "cubic-bezier(0.77, 0, 0.175, 1)";

const WORLD_SETTING_ORBIT = {
  cx: 266,
  cy: 286,
  rx: 240,
  ry: 59,
  rotation: -22,
} as const;
const WORLD_SETTING_GLOBE = {
  cx: 266,
  cy: 286,
  shellRadius: 142,
  landRadius: 138,
  orbitOcclusionRadius: 146,
  landScale: 1.173553719,
} as const;
const WORLD_SETTING_LAND_SOURCE = {
  cx: 250,
  cy: 306,
} as const;
export const WORLD_SETTING_MOTION_PROGRAM: AgentRoleMotionProgram = {
  workingEntryTimeMs: 288,
  working: [
    {
      part: "land-strip",
      keyframes: [
        { offset: 0, transform: "translateX(0px)" },
        { offset: 1, transform: "translateX(-242px)" },
      ],
      options: {
        duration: 5_600,
        iterations: Infinity,
        easing: "linear",
      },
    },
    {
      part: "accent-star",
      keyframes: [
        { offset: 0, opacity: 0.84, transform: "scale(1)" },
        {
          offset: 0.1,
          opacity: 0.84,
          transform: "scale(1)",
          easing: INTERVAL_EASING,
        },
        {
          offset: 0.16,
          opacity: 1,
          transform: "scale(1.08)",
          easing: INTERVAL_EASING,
        },
        { offset: 0.22, opacity: 0.84, transform: "scale(1)" },
        { offset: 1, opacity: 0.84, transform: "scale(1)" },
      ],
      options: {
        duration: 5_600,
        iterations: Infinity,
        easing: "linear",
      },
    },
  ],
  waiting: [],
};

// Simplified offline from Natural Earth 1:110m land data (public domain).
const WORLD_SETTING_LAND_ATLAS_PATH = [
  "M220.5 356.9L222.3 357.7L219.5 358.4L215.8 355.9L218.2 357.1L219.4 355.6L220.1 356.1Z",
  "M226.6 354.3L227 355L224.9 355L226.2 354.6Z",
  "M313.2 352.9L312.2 353L312.3 351.9L313.4 352.5Z",
  "M363.7 344.5L365.7 344.6L364.7 347.2L363.3 344.4Z",
  "M382.3 344.6L383.1 345.1L382.3 347.4L379.8 350.1L378 349.7L382.2 344.2Z",
  "M383.4 340.1L384.8 341.8L386 341.6L383.8 345.4L382.8 343.3L383.4 341.3L382 338.6L383.2 339.3Z",
  "M299.6 318.8L298 328.5L296.5 330.2L295.1 327.5L295.6 322.4L299.1 317.4L299.5 318.2Z",
  "M362.5 319L363.7 320.2L364.4 323.9L368.9 330.6L368.8 335.9L366.8 341.3L364.4 342.9L363.5 341.8L362.5 342.7L360.5 341.9L358.9 338.5L358 339.3L358.6 337.1L357.4 339L356.3 336.8L354.3 335.7L345.3 339.1L343.3 338.3L343.8 335.9L342.2 330.7L342.7 326.5L342.8 327.3L347.2 324.6L350.5 319.4L353.1 320.1L353.8 317.8L355.1 317.4L354.6 316.6L357.8 317.2L357.1 320.2L360.3 322.7L361.8 316.1L362.5 318.7Z",
  "M349.6 315.6L349.3 314.8L351.6 313.9L350.1 314.9Z",
  "M345.3 313.6L346.1 314.2L344.5 314.5L345.1 314Z",
  "M339 312.4L340.5 312.1L343.8 313.9L336.8 312.5L337.3 311.6L338.9 312.1Z",
  "M368.2 311.2L367 312L365.7 311.4L367.4 311.2L367.9 309.9L368.4 310.6Z",
  "M353.7 308.9L354 309.6L352 309.2L353 308.6Z",
  "M356.2 307.1L357.1 309.2L359 307.6L363.2 309.6L367.3 316L365.4 315.6L363.3 313.2L361.9 314.8L358.5 313.9L358.7 311.1L355.9 309.3L355.4 309.9L354.7 308.7L355.9 308.1L353.7 306.9L356.1 306.7Z",
  "M350.2 304.7L349.1 305.8L346.8 305.8L347.3 307.3L348.9 306.6L347.7 307.8L348.8 311L347.3 308.5L346.5 311.4L345.8 308.6L346.7 305.5L350.1 304.4Z",
  "M352.5 304.9L352.1 306.8L352 303.9L352.4 304.5Z",
  "M337.1 311.5L335 310L330.1 300.8L331.5 301L334.9 304.7L337.2 310.1Z",
  "M345.2 304.3L346 305.1L345.2 305.3L344.1 309.8L340.1 308.8L339.3 304.7L342 303.1L344.5 299.5L346.1 300.9L344.9 302.9L345.4 303.8Z",
  "M351 298.1L350.3 300.7L349.1 298.6L348.1 299.5L350.3 296.8L350.9 297.7Z",
  "M320.6 300.1L319.7 299.6L319.9 296.7L320.9 299.9Z",
  "M345.7 297.2L344.8 298.1L346.3 295.3L346 296.6Z",
  "M347.9 294.8L348.8 295.1L348 296.1L348 295.2Z",
  "M347.6 288.5L348.4 289.9L347.8 292.5L349.3 293L349.4 294.2L347.1 292.9L347.1 288.5Z",
  "M217.2 287.2L220.1 288.4L216.3 289L216 288.4L217.4 288.4L216.8 287.2Z",
  "M340.2 288.4L339 288.5L339 287.7L340.5 287L340.3 287.8Z",
  "M212.4 284.5L216.1 287.1L213.7 287.2L213.1 285.6L211 284.6L208.9 285.3L211.8 284.2Z",
  "M347.5 284.5L347.2 285.3L346.7 283.8L347.7 282.1L347.9 283Z",
  "M356.5 273.7L355.4 275.1L355 274.4L356 273.5Z",
  "M276.4 269.9L276.2 271.4L274.4 270.5L275.9 270Z",
  "M360.8 270.9L360.3 272.8L357.3 274.4L356.8 273.3L354.1 274L354.7 274.7L353.5 276.3L353 274.6L355.1 272.5L357.2 272.4L361 266.9L360.8 269.9Z",
  "M362.7 264.3L363.7 264.1L363.8 265.1L360.1 266.7L361.4 263L362.2 264Z",
  "M183 260.2L179.7 258L182.7 259.7Z",
  "M228.3 258.1L227.8 259L230.1 259.5L230.3 261.9L229.5 260.9L228.8 261.7L226.2 261L228.6 257.5Z",
  "M362.6 258.1L363.2 259.7L362.2 259.4L362.5 262.4L361.5 262.6L361.9 254.7L362.3 257.1Z",
  "M261.4 256.6L259.3 257.1L259.5 255.1L261.5 253.9L261.9 255.8Z",
  "M274.5 253.5L274.1 254.2L273.4 253.7L274.3 253Z",
  "M264 250.6L263.3 251.6L264.7 251.5L263.9 253.1L267.1 256.2L267 257.6L262.5 258.8L263.7 257.4L262.5 256.9L262.9 255.5L264 255L261.9 252.4L263.2 250.7Z",
  "M208.8 244L212.2 245.8L207.4 246L208.3 243.9Z",
  "M256.2 243.2L256.9 244.5L253.5 246L250.7 245.6L251.4 245.2L249.9 244.7L251.1 244.3L249.6 244L255.1 243.2Z",
  "M215 242.6L214.2 242.6L214.4 241.6L215.4 242.3Z",
  "M148.4 243.1L150.5 242.8L151.8 243.7L150 244.2L149.7 245.3L145.9 243.6L145 244.6L145 240.9L148.4 242.5Z",
  "M201.7 240.7L198.9 240.5L200 239.8L201.3 240.4Z",
  "M205.1 240.4L205.1 241.3L206 240.6L207.3 242.5L208.5 240L210.5 240.2L211.4 242.2L208.3 243.1L203.4 247.4L202.4 250.3L204 252.1L210.7 253.9L212.3 257.6L213.2 256.4L212.3 254.4L214.5 252.6L213.2 250.5L214 249.5L213.5 247.1L216.4 247L219.2 248.3L219.4 250.3L220.5 251L222.6 249L224.5 252.8L227.5 254.4L228.6 256.8L225.6 258.5L221.4 258.6L218.2 261.8L222.3 259.5L222.7 262.3L224.6 262.7L225.3 261.6L225.8 262.6L222.1 264.9L221.5 264L222.7 263.2L218.9 264.7L219 266.7L216.5 267.3L217.6 267.3L216.3 267.5L215.6 269.2L215.2 268.7L215 270.9L214.7 269L215.1 272.4L211.3 276.3L212 282.2L209.5 277.6L206.1 277.4L205.4 278.5L202.9 277.9L201.1 279.3L200.2 284.8L201.3 287.8L202.5 288.9L204.1 288.3L205.3 286.2L207.5 285.7L206.2 291L209.9 291.6L209.7 295.5L211.3 297.7L212.5 296.9L214.3 297.8L215.6 295.5L217.8 294.3L217.8 297.4L219 294.5L220.2 296L224.4 295.9L224.1 296.6L227.6 300.4L229.7 300.6L231.5 302L232.1 306.1L235.8 307.5L236 308.5L239.1 308.7L242.1 310.9L242.7 312.9L240 318.3L238.5 326.7L234 329.5L233.1 333.1L229.8 338.5L228.2 338.9L226.7 338L227.8 340.9L226.2 342.6L224.1 342.7L223.8 344.7L222.2 344.8L223.3 346.2L220.8 349L221.6 351.5L219.5 353.9L220.2 355.4L218.3 356.8L215.6 355.4L215.2 352L216.2 350.3L215.2 350.1L217.1 346L216 346.8L218.8 324.7L218 322.4L214.9 319.8L211.4 311.8L212.4 308.5L211.6 307L214.2 302.4L213.4 298.1L212.5 297.6L211.6 299.2L208.4 296.6L207.2 293.4L196.4 288.7L195.1 287.2L194.7 284.5L188.8 276L192.2 284.4L190.6 282.6L187.2 274.8L184.9 273.3L182.4 267.9L182.2 260.5L183.6 261.5L183.4 259.7L180.3 258L175.9 251.1L167.1 248.5L164 250.1L164.7 248.1L159.5 253.1L155.2 254.6L160 251.6L160.4 250.4L157.1 250.6L157.2 249.7L154.3 247.9L155.4 246.4L157.9 245.8L157.9 244.8L155.1 245.1L153 244L157.3 243.6L153.9 241.4L160.7 238.6L174.2 240.9L179.9 239.4L192.8 242.4L193.3 241.2L194.6 241L197.8 242.1L200.3 241.2L201.4 242.4L202.7 240.8L201.1 239.8L202 238.1L203.6 238.6L204.5 239.7L203.9 240.2Z",
  "M189.3 236.9L192.1 237.1L193.3 238.3L193.1 237L194.4 237L198 240.3L196.9 240.4L197.1 241.1L187.9 240.7L187.1 239.9L190.4 239.5L186.7 239.4L187.9 238.7L185.7 238.4L188.6 236.8Z",
  "M214.7 237L211.6 236.7L213.5 236.4Z",
  "M207.8 236.9L208.3 237.5L210.7 236.3L211.7 237.9L213.7 237.3L220.3 239.8L221 240.7L219.7 241.1L224.4 242.9L223 244.6L220.3 243.4L222.3 246.8L219.8 245.8L221.5 247.5L215.7 244.9L213.2 245L216.3 244.2L217 242L212.9 239.7L205.8 239.2L206.5 238.7L205.6 238.7L205.9 236.9L208.3 236.3Z",
  "M198.5 236.3L200.5 236.3L201 238.3L199.2 238.6L197.1 237.5L198.5 237.3L197.7 236.7Z",
  "M203.4 237.3L201.9 237.9L201.5 236.6L205.2 236.2L204.2 237.1Z",
  "M185 238.6L183.3 239L181.3 238.1L182.7 236.4L182 235.8L188.4 236.6L185 238.2Z",
  "M363.5 234.6L359.4 235.5L358.1 234.9L361.1 234.1Z",
  "M199.8 233.5L200 235.2L197.1 234.6L197.1 233.9L199.7 233.7Z",
  "M193.3 234L194.9 234.7L190.6 235.7L189.5 235.4L190.8 235L186.9 235L188.4 233.8L192.7 234.7L191.7 233.8L193 233.6Z",
  "M304.7 239.2L302.1 239.2L300.6 238L303.4 235.1L312.3 233.7L305.3 235.8L303.4 238.4Z",
  "M202.4 233.2L212.3 235.2L203.9 235.3L201 233.1Z",
  "M187.9 232.7L187.3 233.7L183.4 234.1L187 232.8Z",
  "M337.9 233.3L342.7 234.4L339.5 235.9L348.8 237.1L348.9 236.4L351.4 236.5L354.3 239.1L354.9 238.2L360 238.5L359.5 237.6L360.4 237.2L372.9 239.1L374.2 240.4L378.8 240.3L380 241.1L380.6 239.8L386.1 240.5L387 240.9L387 244.6L385.3 245L386.7 246.9L382.8 247.8L380.5 249.4L379.5 248.8L375.9 249.5L374.9 251L375.7 251.6L375 254.2L371.4 257.8L370.8 252.4L376.6 246.9L373.6 248.8L373.1 247.7L371.4 248L369.7 249.6L370.2 250.1L361.6 250.2L356.8 254.3L360 254.8L361 256.7L358.9 262.3L351.7 268.5L352.8 272.9L351 273.5L350.2 268.6L347.4 269.3L347.8 267.3L345.4 269L345.9 270.6L348.3 270.6L346.1 273L347.9 276.1L347.8 279.3L343.9 284.5L340.5 285.8L340.2 286.8L339 285.5L337.2 287.3L339.5 293.3L339.4 295L336.7 297.9L336.6 296.6L333.3 293.3L332.7 297.3L335.2 300.8L336.1 304.8L334.2 303.4L332.1 298.6L331.3 290L329.3 290.9L329.4 288.8L327.5 284.5L324.5 285.7L320 291L319.7 296.2L318.1 298.5L315.4 290.9L314.8 285.8L313.4 286.3L310.6 282L304.6 281.7L304 280.4L302.8 281L300.6 279.7L299.7 277.5L298.2 277.7L300.8 283.3L302.3 283.2L303.9 281.1L304.2 283.1L306.2 284.9L303.2 289.7L295.2 294.1L294.7 290.2L289.3 279.5L289.5 278.1L288.8 279.9L287.8 277.8L291.2 288.4L295.1 294.3L294.7 294.9L296 296.1L300.4 294.6L300.3 296L298.1 302L292.4 310.4L293.4 319.9L289.4 324.7L289.8 328.8L287.9 330.3L287.6 333.2L285 337L279.2 338.9L273.9 323.1L275.2 316.1L274 310.8L271.9 307L272.3 302.5L271.7 301.5L270 302L268.9 300.1L264.7 301.6L259.9 301.4L254.8 294.5L254.6 285.3L262 272.2L264.5 272.8L267 271.4L272.4 270.7L273.5 271.1L273 274.1L278.8 277.4L280.5 275L285.4 276.8L288.7 276.8L290.3 271.4L284.6 271.4L283.6 268.7L288.5 266.3L291.8 267.3L294 266.4L290.7 263.3L292.3 261.4L289.5 262.3L290.4 263.4L288.8 264.1L287.8 263.2L288.4 262.5L286.7 262L284.6 265.8L285.4 267.2L281.2 268L282.2 270.4L281.1 271.6L279.1 266.6L274.8 262.8L274.5 264.4L278.4 268.1L277.3 267.8L276.8 270.1L276.4 268.2L272 264.1L268.1 265.3L264.6 271.4L262.4 272.1L260 271.2L259.7 265.4L265.1 264.4L265.2 262.5L262.9 260L264.9 260.1L264.7 259L266.9 258.7L269.2 255.9L271.5 255.4L271.7 252.1L273.1 251.5L272.5 253.6L273.4 255L279.2 254.6L280.3 253.9L280.5 251.8L282.2 252.1L281.7 250.1L285.6 249.3L281.4 249.5L280.3 248.7L280.5 246.3L283.1 244.5L280.9 243.9L278 246.7L277.5 248.1L278.6 249.3L276.7 253L274.7 253.7L273 249.8L271.6 250.9L269.8 250.7L269.4 247.5L275.9 242L282.5 238.9L284.9 238.8L287 239.5L286.2 239.7L286.9 240.3L293.1 241.8L293.6 242.9L292.9 243.4L288.3 243.1L290.9 245.7L291 244.5L292.6 245.1L294.3 243.2L295.5 243.6L295.2 241.2L297.1 241.5L297.2 243L302.1 241L306.3 241.5L306.7 240L312.1 241.7L310.8 238.9L312.5 237.2L314.8 237.3L314.3 238.6L315.5 241.4L313.9 243.4L314.7 243.5L316.5 242L315.1 238.5L316.2 237.2L317.3 238.8L317 238.1L318.1 237.7L320.8 238.2L320.1 236.4L337.3 232.9L336.4 233.2Z",
  "M299 267L299.9 268L299.1 270.5L302.2 271.1L301.4 268.2L302.8 267.3L302.1 266.2L301.5 267.1L299.8 263.9L301.7 263.3L301.7 261.7L299 262.2L297.4 263.9L298.7 266.5Z",
  "M198.7 232L195.3 232L195.9 231.7L195.1 231.1L198.2 231.6Z",
  "M336.6 232L332.8 232.4L334.6 231.1L336.8 231.7Z",
  "M278.3 230.7L280.5 231.4L276.7 233.5L273 230.8L277.4 230.4Z",
  "M283.1 230.1L284.4 230.4L281.5 231L277.7 230.1L281.4 229.8Z",
  "M333.2 231.5L327.3 230.1L330.5 229.3L333.3 230.7Z",
  "M207.5 230.8L208.3 231.1L205 232.1L201 230.3L203.9 229.3L207 230.1Z",
  "M220 227.5L224.4 228.2L214.3 231.1L215.3 231.8L211.8 234.1L205.8 233.8L206.7 232.4L208.9 232.8L206.9 232L208.8 231.1L207.6 230.2L211 230L207.1 230L204.4 228.7L218.5 227.5Z",
  "M247.8 227.1L252 227.9L244.6 228.4L257.8 229.2L252.5 230.3L254.1 230.3L252.8 231.6L253.6 233.3L251.4 233.6L252.7 234.1L252.1 235L253 235.8L250.2 236.8L251 237.8L249.3 237.7L251.4 239.3L248.8 238.5L248.3 239.7L251 239.8L239.2 244.2L237.2 246.8L236.8 249.2L233.6 248.5L231.3 245.9L229.7 242.5L231.8 240L229.2 240.3L229.5 239.1L231.5 239.4L228.5 238.3L229.2 237.4L226.6 234.7L219.9 234.2L218 233.3L221.1 232.9L216.7 232.3L221.8 231L220.3 230.3L223.9 228.8L232.1 228.1L236.1 228.9L234.6 228L242.4 227Z",
].join("");

function LandMasses() {
  return (
    <path
      data-land-atlas="natural-earth-110m"
      d={WORLD_SETTING_LAND_ATLAS_PATH}
      fill="#7899E2"
    />
  );
}

interface WorldSettingAnimationProps {
  motionState: AgentRoleMotionState;
}

export default function WorldSettingAnimation({
  motionState,
}: WorldSettingAnimationProps) {
  const rootRef = useRef<SVGSVGElement>(null);
  const idPrefix = useId().replaceAll(":", "");
  const landClipId = `${idPrefix}-world-land`;
  const landLimbGradientId = `${idPrefix}-world-land-limb-gradient`;
  const landLimbMaskId = `${idPrefix}-world-land-limb-mask`;
  const orbitBackMaskId = `${idPrefix}-world-orbit-back`;
  const orbitFrontClipId = `${idPrefix}-world-orbit-front`;
  useAgentRoleMotion(rootRef, motionState, WORLD_SETTING_MOTION_PROGRAM);

  return (
    <svg
      ref={rootRef}
      viewBox="0 0 512 512"
      aria-hidden="true"
      data-agent-role="world-setting"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <clipPath id={landClipId} clipPathUnits="userSpaceOnUse">
          <circle
            data-land-clip="true"
            cx={WORLD_SETTING_GLOBE.cx}
            cy={WORLD_SETTING_GLOBE.cy}
            r={WORLD_SETTING_GLOBE.landRadius}
          />
        </clipPath>
        <radialGradient
          id={landLimbGradientId}
          gradientUnits="userSpaceOnUse"
          cx={WORLD_SETTING_GLOBE.cx}
          cy={WORLD_SETTING_GLOBE.cy}
          r={WORLD_SETTING_GLOBE.landRadius}
        >
          <stop offset="0.72" stopColor="#FFFFFF" />
          <stop offset="0.9" stopColor="#FFFFFF" stopOpacity="0.82" />
          <stop offset="1" stopColor="#000000" />
        </radialGradient>
        <mask
          id={landLimbMaskId}
          maskUnits="userSpaceOnUse"
          x="0"
          y="0"
          width="512"
          height="512"
        >
          <rect width="512" height="512" fill="#000000" />
          <circle
            cx={WORLD_SETTING_GLOBE.cx}
            cy={WORLD_SETTING_GLOBE.cy}
            r={WORLD_SETTING_GLOBE.landRadius}
            fill={`url(#${landLimbGradientId})`}
          />
        </mask>
        <mask
          id={orbitBackMaskId}
          maskUnits="userSpaceOnUse"
          x="0"
          y="0"
          width="512"
          height="512"
        >
          <rect width="512" height="512" fill="#FFFFFF" />
          <circle
            cx={WORLD_SETTING_GLOBE.cx}
            cy={WORLD_SETTING_GLOBE.cy}
            r={WORLD_SETTING_GLOBE.orbitOcclusionRadius}
            fill="#000000"
          />
        </mask>
        <clipPath id={orbitFrontClipId} clipPathUnits="userSpaceOnUse">
          <rect
            x="0"
            y={WORLD_SETTING_ORBIT.cy}
            width="512"
            height={512 - WORLD_SETTING_ORBIT.cy}
          />
        </clipPath>
      </defs>
      <g data-part="base">
        <path
          d="M98 386a21 21 0 1 0 0 42 21 21 0 0 0 0-42Z"
          fill="#738FCD"
          stroke="#A6BDF2"
          strokeWidth="7"
        />
        <path
          d="M128 430c67 39 157 43 235 9"
          fill="none"
          stroke="#F8FAFF"
          strokeDasharray="3 22"
          strokeLinecap="round"
          strokeWidth="7"
        />
        <path
          d="M363 439c41-18 75-47 96-83"
          fill="none"
          stroke="#FFB323"
          strokeDasharray="3 21"
          strokeLinecap="round"
          strokeWidth="7"
        />
      </g>

      <g data-part="orbit-back" mask={`url(#${orbitBackMaskId})`}>
        <ellipse
          cx={WORLD_SETTING_ORBIT.cx}
          cy={WORLD_SETTING_ORBIT.cy}
          rx={WORLD_SETTING_ORBIT.rx}
          ry={WORLD_SETTING_ORBIT.ry}
          fill="none"
          stroke="#FAFBFF"
          strokeWidth="9"
          transform={`rotate(${WORLD_SETTING_ORBIT.rotation} ${WORLD_SETTING_ORBIT.cx} ${WORLD_SETTING_ORBIT.cy})`}
        />
        <path
          d="M318 175c22-22 43-43 63-66"
          fill="none"
          stroke="#FAFBFF"
          strokeDasharray="3 18"
          strokeLinecap="round"
          strokeWidth="7"
        />
      </g>

      <g data-part="globe-shell">
        <circle
          data-globe-disk="true"
          cx={WORLD_SETTING_GLOBE.cx}
          cy={WORLD_SETTING_GLOBE.cy}
          r={WORLD_SETTING_GLOBE.shellRadius}
          fill="#17202C"
          fillOpacity="0.18"
        />
        <circle
          cx={WORLD_SETTING_GLOBE.cx}
          cy={WORLD_SETTING_GLOBE.cy}
          r={WORLD_SETTING_GLOBE.shellRadius}
          fill="none"
          stroke="#88A8ED"
          strokeWidth="8"
        />
      </g>

      <g data-part="land-window" clipPath={`url(#${landClipId})`}>
        <g
          data-land-limb-mask="true"
          mask={`url(#${landLimbMaskId})`}
        >
          <g
            data-land-scale="true"
            transform={`translate(${WORLD_SETTING_GLOBE.cx} ${WORLD_SETTING_GLOBE.cy}) scale(${WORLD_SETTING_GLOBE.landScale}) translate(-${WORLD_SETTING_LAND_SOURCE.cx} -${WORLD_SETTING_LAND_SOURCE.cy})`}
          >
            <g
              data-land-projection="true"
              transform="translate(250 306) rotate(-8) scale(1 0.82) translate(-250 -306)"
            >
              <g data-part="land-strip" style={MOVING_PART_STYLE}>
                <g data-land-copy="primary"><LandMasses /></g>
                <g data-land-copy="wrapped" transform="translate(242 0)">
                  <LandMasses />
                </g>
              </g>
            </g>
          </g>
        </g>
      </g>

      <g
        data-part="orbit-front"
        clipPath={`url(#${orbitFrontClipId})`}
        transform={`rotate(${WORLD_SETTING_ORBIT.rotation} ${WORLD_SETTING_ORBIT.cx} ${WORLD_SETTING_ORBIT.cy})`}
      >
        <ellipse
          cx={WORLD_SETTING_ORBIT.cx}
          cy={WORLD_SETTING_ORBIT.cy}
          rx={WORLD_SETTING_ORBIT.rx}
          ry={WORLD_SETTING_ORBIT.ry}
          fill="none"
          stroke="#FAFBFF"
          strokeWidth="9"
        />
      </g>

      <g data-part="upper-orbit-node">
        <circle
          cx="446"
          cy="173"
          r="19"
          fill="#7899E2"
          stroke="#A6BDF2"
          strokeWidth="3"
        />
        <path
          d="M474 174c14 6 18 18 12 31-4 10-12 18-23 26"
          fill="none"
          stroke="#FAFBFF"
          strokeLinecap="round"
          strokeWidth="7"
        />
      </g>

      <g data-part="accent-star" style={ACCENT_STAR_STYLE}>
        <path
          d="m397 48 9 27 28 9-28 9-9 29-9-29-28-9 28-9 9-27Z"
          fill="#FFB323"
        />
        <circle cx="397" cy="84" r="7" fill="#FFD26A" />
      </g>
    </svg>
  );
}
