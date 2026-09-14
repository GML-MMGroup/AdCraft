# 001 — Smooth the dual-orbit generation loader

- **Status**: DONE
- **Commit**: f5aa1e4f
- **Severity**: MEDIUM
- **Category**: Easing & duration; Physicality & origin
- **Estimated scope**: 2 files, approximately 90 lines

## Problem

The media-generation Loader correctly reaches all four card quadrants, but it uses four large route segments and an overshooting curve on every segment:

```css
/* apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.css:705 — current */
animation:
  agent-canvas-node-dots-morph 4.2s cubic-bezier(0.35, 1.55, 0.65, 1) infinite,
  agent-canvas-node-dots-breathe 1.9s cubic-bezier(0.66, 0, 0.34, 1) infinite;
```

The `1.55` Y control point causes each 25% segment to overshoot and settle. A complete orbit therefore feels like four launches rather than one continuous circulation. Both masks also use the same four waypoints, so their large overlapping areas read as one synchronized bright mass.

## Target

Use eight linearly interpolated waypoints over `6.4s`. The first mask follows a rounded outer clockwise route; the second follows a smaller clockwise route with a phase lead. The changing separation lets their soft edges alternately read as two regions and one merged region without adding DOM layers.

Keep the existing gradients and mask falloff. Replace the base mask geometry and animation declaration with:

```css
.agent-canvas-node__generation-dots--dynamic {
  mask-size: 52% 46%, 38% 38%;
  mask-position: 16.7% 20.4%, 58.1% 19.4%;
  -webkit-mask-size: 52% 46%, 38% 38%;
  -webkit-mask-position: 16.7% 20.4%, 58.1% 19.4%;
  animation:
    agent-canvas-node-dots-morph 6.4s linear infinite,
    agent-canvas-node-dots-breathe 2.4s cubic-bezier(0.66, 0, 0.34, 1) infinite;
}
```

Replace the keyframes with these exact values, including the WebKit mirror:

```css
@keyframes agent-canvas-node-dots-morph {
  0%, 100% {
    mask-size: 52% 46%, 38% 38%;
    mask-position: 16.7% 20.4%, 58.1% 19.4%;
    -webkit-mask-size: 52% 46%, 38% 38%;
    -webkit-mask-position: 16.7% 20.4%, 58.1% 19.4%;
  }
  12.5% {
    mask-size: 50% 50%, 42% 40%;
    mask-position: 50% 6%, 74.1% 31.7%;
    -webkit-mask-size: 50% 50%, 42% 40%;
    -webkit-mask-position: 50% 6%, 74.1% 31.7%;
  }
  25% {
    mask-size: 46% 58%, 44% 38%;
    mask-position: 83.3% 16.7%, 80.4% 53.2%;
    -webkit-mask-size: 46% 58%, 44% 38%;
    -webkit-mask-position: 83.3% 16.7%, 80.4% 53.2%;
  }
  37.5% {
    mask-size: 54% 52%, 42% 44%;
    mask-position: 100% 54.2%, 65.5% 76.8%;
    -webkit-mask-size: 54% 52%, 42% 44%;
    -webkit-mask-position: 100% 54.2%, 65.5% 76.8%;
  }
  50% {
    mask-size: 60% 44%, 38% 46%;
    mask-position: 82.5% 83.9%, 40.3% 87%;
    -webkit-mask-size: 60% 44%, 38% 46%;
    -webkit-mask-position: 82.5% 83.9%, 40.3% 87%;
  }
  62.5% {
    mask-size: 54% 50%, 44% 42%;
    mask-position: 43.5% 98%, 21.4% 67.2%;
    -webkit-mask-size: 54% 50%, 44% 42%;
    -webkit-mask-position: 43.5% 98%, 21.4% 67.2%;
  }
  75% {
    mask-size: 48% 54%, 46% 40%;
    mask-position: 13.5% 82.6%, 16.7% 43.3%;
    -webkit-mask-size: 48% 54%, 46% 40%;
    -webkit-mask-position: 13.5% 82.6%, 16.7% 43.3%;
  }
  87.5% {
    mask-size: 50% 48%, 40% 38%;
    mask-position: 0% 46.2%, 36.7% 25.8%;
    -webkit-mask-size: 50% 48%, 40% 38%;
    -webkit-mask-position: 0% 46.2%, 36.7% 25.8%;
  }
}

@keyframes agent-canvas-node-dots-breathe {
  0%, 100% { opacity: 0.62; }
  50% { opacity: 0.88; }
}
```

## Repo conventions to follow

- Keep the existing static/dynamic two-span structure in `AgentCanvasMediaGenerationLoader.tsx`.
- Keep `contain: paint`, `isolation: isolate`, viewport culling, interaction pause, and the existing reduced-motion rule.
- Continuous progress motion uses `linear`; the independent opacity breath retains the existing `cubic-bezier(0.66, 0, 0.34, 1)`.
- Exact CSS values are locked in `apps/web/src/features/agent-canvas/canvas/AgentCanvasNode.test.tsx`.

## Steps

1. Update the focused CSS assertions in `AgentCanvasNode.test.tsx` to require eight waypoints, `6.4s linear`, `2.4s` breathing, and `0.62/0.88` opacity.
2. Run `npm run test -- AgentCanvasNode.test.tsx` and confirm the current four-point, overshooting animation fails.
3. Replace the base Mask state, animation declaration, morph keyframes, and breathe keyframes in `AgentCanvasNode.css` with the exact target above.
4. Re-run the focused test and confirm all tests pass.
5. Use Chromium DevTools Animation playback at 10% speed and verify there is no visible settle or relaunch at 12.5% increments.

## Boundaries

- Do NOT change Loader markup, node status checks, media mounting, API behavior, dot gradients, mask gradients, card dimensions, or background color.
- Do NOT add dependencies, JavaScript animation loops, blur filters, or additional layers.
- If the existing CSS no longer matches the cited two-layer implementation, stop and report drift.

## Verification

- **Mechanical**: `npm run test -- AgentCanvasNode.test.tsx`; `npm run typecheck`; focused ESLint; `npm run build`.
- **Feel check**: observe square, landscape, and portrait working nodes for at least two complete `6.4s` loops at normal speed and 10% speed. Confirm the bright region circulates continuously clockwise, never snaps at a waypoint, and still reads as active generation rather than a decorative spinner.
- **Performance check**: record four visible working media nodes for 15 seconds. Confirm the implementation retains two layers and does not introduce layout work or JavaScript animation callbacks.
- **Done when**: all eight computed Mask states match the target, the loop closes without a jump, and the four-corner lunge is no longer perceptible.
