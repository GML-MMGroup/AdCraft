import { createRoot } from "react-dom/client";

import ProductDesignerAnimation, {
  PRODUCT_DESIGNER_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/ProductDesignerAnimation.tsx";
import PropDesignerAnimation, {
  PROP_DESIGNER_MOTION_PROGRAM,
} from "../../src/features/agent-canvas/chat/agent-role-animation/roles/PropDesignerAnimation.tsx";
import type {
  AgentRoleMotionProgram,
  AgentRoleMotionTrack,
} from "../../src/features/agent-canvas/chat/agent-role-animation/types.ts";

const ROLE_DEFINITIONS = {
  product: {
    slug: "product-designer",
    component: ProductDesignerAnimation,
    program: PRODUCT_DESIGNER_MOTION_PROGRAM,
  },
  prop: {
    slug: "prop-designer",
    component: PropDesignerAnimation,
    program: PROP_DESIGNER_MOTION_PROGRAM,
  },
} as const;

const REVEAL_CASES = {
  "product-glass-sweep": { role: "product", part: "glass-sweep" },
  "prop-guide-horizontal": { role: "prop", part: "guide-active-horizontal" },
  "prop-guide-vertical": { role: "prop", part: "guide-active-vertical" },
  "prop-guide-cross": { role: "prop", part: "guide-active-cross" },
} as const;

type RevealCaseName = keyof typeof REVEAL_CASES;
type RoleName = keyof typeof ROLE_DEFINITIONS;

interface PreparedReveal {
  clipId: string;
  part: string;
  role: RoleName;
  sampleTimeMs: number;
  targetMatrixDelta: number;
  windowMatrixDelta: number;
}

interface PixelEvidence {
  outsideClipPixels: number;
  paintedBounds: { bottom: number; left: number; right: number; top: number };
  paintedPixels: number;
}

interface ActiveReveal {
  animation: Animation;
  clipShape: SVGGeometryElement;
  container: HTMLElement;
  originalCssText: Map<SVGElement | HTMLElement, string>;
  root: SVGSVGElement;
}

let activeReveal: ActiveReveal | null = null;

function matrixValues(matrix: DOMMatrixReadOnly): number[] {
  return [matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f];
}

function matrixDelta(before: DOMMatrixReadOnly, after: DOMMatrixReadOnly): number {
  const beforeValues = matrixValues(before);
  const afterValues = matrixValues(after);
  return Math.max(...beforeValues.map((value, index) => (
    Math.abs(afterValues[index] - value)
  )));
}

function computedTransform(element: SVGGraphicsElement): DOMMatrixReadOnly {
  const transform = getComputedStyle(element).transform;
  return new DOMMatrixReadOnly(transform === "none" ? undefined : transform);
}

function translationMagnitude(matrix: DOMMatrixReadOnly): number {
  return Math.hypot(matrix.e, matrix.f);
}

function maximumNativeTranslationTime(
  animation: Animation,
  target: SVGGraphicsElement,
  track: AgentRoleMotionTrack,
): number {
  const duration = Number(track.options.duration);
  let maximum = { distance: Number.NEGATIVE_INFINITY, time: 0 };
  for (let step = 0; step <= 400; step += 1) {
    const time = duration * step / 400;
    animation.currentTime = time;
    const distance = translationMagnitude(computedTransform(target));
    const opacity = Number(getComputedStyle(target).opacity);
    if (opacity > 0.1 && distance > maximum.distance) {
      maximum = { distance, time };
    }
  }
  return maximum.time;
}

function findRoot(role: RoleName): SVGSVGElement {
  const root = document.querySelector<SVGSVGElement>(
    `[data-agent-role="${ROLE_DEFINITIONS[role].slug}"]`,
  );
  if (!root) throw new Error(`Missing ${role} artwork`);
  return root;
}

function rememberStyle(
  originals: Map<SVGElement | HTMLElement, string>,
  element: SVGElement | HTMLElement,
): void {
  if (!originals.has(element)) originals.set(element, element.style.cssText);
}

async function prepareReveal(name: RevealCaseName): Promise<PreparedReveal> {
  restoreReveal();
  const definition = REVEAL_CASES[name];
  const roleDefinition = ROLE_DEFINITIONS[definition.role];
  const root = findRoot(definition.role);
  const target = root.querySelector<SVGGElement>(
    `[data-part="${definition.part}"]`,
  );
  const track = roleDefinition.program.working.find(({ part }) => (
    part === definition.part
  ));
  if (!target || !track) throw new Error(`Missing reveal target ${name}`);

  const clipOwner = target.closest<SVGGElement>("g[clip-path]");
  const clipId = clipOwner?.getAttribute("clip-path")
    ?.match(/^url\(#(.+)\)$/)?.[1];
  const clipShape = root.querySelector<SVGGeometryElement>(
    `clipPath[id="${clipId}"] > *`,
  );
  const container = root.parentElement;
  if (!clipOwner || !clipId || !clipShape || !container) {
    throw new Error(`Missing clip window for ${name}`);
  }

  const originalCssText = new Map<SVGElement | HTMLElement, string>();
  rememberStyle(originalCssText, container);
  rememberStyle(originalCssText, root);
  container.style.width = "512px";
  container.style.height = "512px";
  root.style.width = "512px";
  root.style.height = "512px";

  for (const shape of root.querySelectorAll<SVGElement>(
    "path, line, rect, ellipse, circle, polygon, polyline",
  )) {
    if (shape.closest("defs")) continue;
    rememberStyle(originalCssText, shape);
    shape.style.visibility = target.contains(shape) ? "visible" : "hidden";
  }
  for (const shape of target.querySelectorAll<SVGElement>(
    "path, line, rect, ellipse, circle, polygon, polyline",
  )) {
    shape.style.stroke = "rgb(255, 255, 255)";
    shape.style.strokeOpacity = "1";
    if (shape.getAttribute("fill") !== "none") shape.style.fill = "rgb(255, 255, 255)";
  }

  const windowBefore = computedTransform(clipOwner);
  const targetBefore = computedTransform(target);

  const animation = target.animate(track.keyframes, {
    ...track.options,
    fill: "both",
  });
  void animation.finished.catch(() => undefined);
  animation.pause();
  const sampleTimeMs = maximumNativeTranslationTime(animation, target, track);
  animation.currentTime = sampleTimeMs;
  await new Promise(requestAnimationFrame);

  const windowAfter = computedTransform(clipOwner);
  const targetAfter = computedTransform(target);

  activeReveal = {
    animation,
    clipShape,
    container,
    originalCssText,
    root,
  };
  return {
    role: definition.role,
    part: definition.part,
    clipId,
    sampleTimeMs,
    targetMatrixDelta: matrixDelta(targetBefore, targetAfter),
    windowMatrixDelta: matrixDelta(windowBefore, windowAfter),
  };
}

async function analyzeRevealPng(base64Png: string): Promise<PixelEvidence> {
  if (!activeReveal) throw new Error("Prepare a reveal before analyzing pixels");
  const { clipShape, container, root } = activeReveal;
  const image = new Image();
  image.src = `data:image/png;base64,${base64Png}`;
  await image.decode();
  const canvas = document.createElement("canvas");
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Missing canvas context");
  context.drawImage(image, 0, 0);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  const containerBounds = container.getBoundingClientRect();
  const clipScreenMatrix = clipShape.getScreenCTM();
  const rootScreenMatrix = root.getScreenCTM();
  if (!clipScreenMatrix || !rootScreenMatrix) throw new Error("Missing clip geometry matrix");
  const toClip = clipScreenMatrix.inverse();
  const toRoot = rootScreenMatrix.inverse();
  let paintedPixels = 0;
  let outsideClipPixels = 0;
  const paintedBounds = {
    left: Number.POSITIVE_INFINITY,
    top: Number.POSITIVE_INFINITY,
    right: Number.NEGATIVE_INFINITY,
    bottom: Number.NEGATIVE_INFINITY,
  };

  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      const index = (y * canvas.width + x) * 4;
      const colorDelta = Math.max(
        Math.abs(pixels[index] - 16),
        Math.abs(pixels[index + 1] - 21),
        Math.abs(pixels[index + 2] - 29),
      );
      if (pixels[index + 3] === 0 || colorDelta < 8) continue;
      paintedPixels += 1;
      const screenPoint = new DOMPoint(
        containerBounds.left + (x + 0.5) * containerBounds.width / canvas.width,
        containerBounds.top + (y + 0.5) * containerBounds.height / canvas.height,
      );
      const rootPoint = screenPoint.matrixTransform(toRoot);
      paintedBounds.left = Math.min(paintedBounds.left, rootPoint.x);
      paintedBounds.top = Math.min(paintedBounds.top, rootPoint.y);
      paintedBounds.right = Math.max(paintedBounds.right, rootPoint.x);
      paintedBounds.bottom = Math.max(paintedBounds.bottom, rootPoint.y);
      if (!clipShape.isPointInFill(screenPoint.matrixTransform(toClip))) {
        outsideClipPixels += 1;
      }
    }
  }

  return { paintedPixels, outsideClipPixels, paintedBounds };
}

function restoreReveal(): void {
  if (!activeReveal) return;
  activeReveal.animation.cancel();
  for (const [element, cssText] of activeReveal.originalCssText) {
    element.style.cssText = cssText;
  }
  activeReveal = null;
}

function App() {
  return (Object.entries(ROLE_DEFINITIONS) as Array<[
    RoleName,
    { component: typeof ProductDesignerAnimation; program: AgentRoleMotionProgram; slug: string },
  ]>).map(([role, definition]) => {
    const Component = definition.component;
    return (
      <div key={role} data-probe-role={role}>
        <Component motionState="idle" />
      </div>
    );
  });
}

Object.assign(window, {
  agentRoleClipProbe: {
    analyzeRevealPng,
    caseNames: Object.keys(REVEAL_CASES) as RevealCaseName[],
    prepareReveal,
    restoreReveal,
  },
});

createRoot(document.getElementById("root")!).render(<App />);
