import type { BrandStageV2 } from "./brandDecisions.ts";

const SKILL_STACK_PATH = "m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5";

// Use the same stage symbols as the Workflow design preview.
const STAGE_ICON_PATHS: Record<BrandStageV2, string> = {
  "brand-memory": "M6.5 3H20v18H6.5A2.5 2.5 0 0 1 4 18.5v-13A2.5 2.5 0 0 1 6.5 3ZM4 18.5A2.5 2.5 0 0 1 6.5 16H20M10 3v8l3-2 3 2V3",
  campaign: "M12 8a4 4 0 1 0 4 4M12 3a9 9 0 1 0 9 9m-9 0 9-9m-5 0h5v5",
  "skill-stack-early": SKILL_STACK_PATH,
  "skill-stack": SKILL_STACK_PATH,
  hypothesis: "m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z",
  "creative-route": "M5 5v14m0-7h8m0 0 5-5m-5 5 5 5",
  adspec: "M4 7h16M4 17h16M8 4v6m8 4v6",
  treatment: "M4 4h16v16H4zM8 4v16M16 4v16M4 8h4m-4 8h4m8-8h4m-4 8h4",
  production: "M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z",
};

export function BrandStageIcon({ stage }: { stage: BrandStageV2 }) {
  return (
    <svg className="brand-decision-panel__stage-icon" width="17" height="17" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="1.55" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false">
      <path d={STAGE_ICON_PATHS[stage]} />
    </svg>
  );
}
