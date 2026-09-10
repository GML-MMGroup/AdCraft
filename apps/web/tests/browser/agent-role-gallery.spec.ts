import { expect, test, type Locator, type Page } from "@playwright/test";

const SCENE_FRAME_TIMES = {
  entry: 120,
  mid: 1_100,
  resolved: 2_300,
} as const;

async function prepareSceneDesigner(page: Page): Promise<Locator> {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.addStyleTag({
    content: '[data-gallery-role="scene"] .gallery-card__state { display: none !important; }',
  });
  await page.getByRole("button", { name: "Scene Designer" }).click();
  await page.getByRole("button", { name: "Idle" }).click();
  await expect.poll(() => page.evaluate(() => (
    document.getAnimations().filter((animation) => {
      const target = (animation.effect as KeyframeEffect | null)?.target;
      return target instanceof Element
        && target.closest('[data-agent-role="scene-designer"]');
    }).length
  ))).toBe(0);
  await page.getByRole("button", { name: "Working" }).click();
  await page.waitForFunction(() => {
    const frameCounts = document.getAnimations().flatMap((animation) => {
      const effect = animation.effect;
      if (!(effect instanceof KeyframeEffect)) return [];

      const target = effect.target;
      if (!(target instanceof Element)
        || !target.closest('[data-agent-role="scene-designer"]')) {
        return [];
      }
      return [effect.getKeyframes().length];
    });
    return frameCounts.filter((count) => count === 5).length === 3
      && frameCounts.filter((count) => count === 3).length === 1;
  });
  return page.locator('[data-gallery-role="scene"] [data-agent-role="scene-designer"]');
}

async function freezeSceneDesignerAt(page: Page, currentTime: number): Promise<void> {
  await page.evaluate((time) => {
    for (const animation of document.getAnimations()) {
      const target = (animation.effect as KeyframeEffect | null)?.target;
      if (target instanceof Element
        && target.closest('[data-agent-role="scene-designer"]')) {
        animation.pause();
        animation.currentTime = time;
      }
    }
  }, currentTime);
}

async function sizeArtwork(artwork: Locator, size: number): Promise<void> {
  await artwork.evaluate((element, artworkSize) => {
    const svg = element as SVGSVGElement;
    svg.style.width = `${artworkSize}px`;
    svg.style.height = `${artworkSize}px`;
    svg.style.overflow = "hidden";
  }, size);
}

test("gallery visibly plays exactly one real role animation and supports manual state control", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-gallery.html");

  const cards = page.locator("[data-gallery-role]");
  await expect(cards).toHaveCount(10);
  await expect(page.locator("[data-gallery-role][data-active='true']")).toHaveCount(1);
  await expect(page.getByTestId("gallery-motion-state")).toHaveText("Working");

  await expect.poll(() => page.evaluate(() => (
    document.getAnimations().filter((animation) => (
      animation.playState === "running"
      && (animation.effect as KeyframeEffect | null)?.target instanceof Element
      && ((animation.effect as KeyframeEffect).target as Element).closest("[data-agent-role]") !== null
    )).length
  ))).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Scene Designer" }).click();
  await expect(page.locator("[data-gallery-role='scene'][data-active='true']")).toHaveCount(1);

  await page.getByRole("button", { name: "Waiting" }).click();
  await expect(page.getByTestId("gallery-motion-state")).toHaveText("Waiting");
  await expect.poll(() => page.evaluate(() => (
    document.querySelectorAll("[data-gallery-role][data-active='true']").length
  ))).toBe(1);

  await page.getByRole("button", { name: "Idle" }).click();
  await expect(page.getByTestId("gallery-motion-state")).toHaveText("Idle");
  await expect.poll(() => page.evaluate(() => (
    document.getAnimations().filter((animation) => (
      (animation.effect as KeyframeEffect | null)?.target instanceof Element
      && ((animation.effect as KeyframeEffect).target as Element).closest("[data-agent-role]") !== null
    )).length
  ))).toBe(0);
});

test("BGM waveform travels right continuously across the complete clock", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.getByRole("button", { name: "BGM Director" }).click();
  await page.getByRole("button", { name: "Idle" }).click();
  await page.getByRole("button", { name: "Working" }).click();
  await page.waitForFunction(() => document.getAnimations().some((animation) => {
    const target = (animation.effect as KeyframeEffect | null)?.target;
    return target instanceof Element
      && target.matches('[data-part="waveform-strip"]')
      && animation.effect?.getTiming().iterations === Infinity;
  }), undefined, { timeout: 2_000 });

  const translations = await page.evaluate(async () => {
    const animation = document.getAnimations().find((candidate) => {
      const target = (candidate.effect as KeyframeEffect | null)?.target;
      return target instanceof Element
        && target.matches('[data-part="waveform-strip"]');
    });
    if (!animation || !(animation.effect instanceof KeyframeEffect)) {
      throw new Error("Missing BGM waveform strip animation");
    }
    const target = animation.effect.target;
    if (!(target instanceof Element)) {
      throw new Error("Missing BGM waveform strip target");
    }

    const samples: number[] = [];
    for (const time of [0, 375, 750, 1_125, 1_500, 1_875, 2_250, 2_625]) {
      animation.pause();
      animation.currentTime = time;
      await new Promise(requestAnimationFrame);
      samples.push(new DOMMatrixReadOnly(getComputedStyle(target).transform).e);
    }
    return samples;
  });

  const expectedTranslations = [-176, -154, -132, -110, -88, -66, -44, -22];
  translations.forEach((translation, index) => {
    expect(translation).toBeCloseTo(expectedTranslations[index], 3);
  });
  expect(translations.slice(1).every((translation, index) => (
    translation > translations[index]
  ))).toBe(true);

  await page.getByRole("button", { name: "Waiting" }).click();
  await expect.poll(() => page.evaluate(() => (
    document.getAnimations().filter((animation) => {
      const target = (animation.effect as KeyframeEffect | null)?.target;
      return target instanceof Element
        && target.closest('[data-agent-role="bgm-director"]');
    }).length
  ))).toBe(0);

  await page.getByRole("button", { name: "Working" }).click();
  await page.getByRole("button", { name: "Idle" }).click();
  await expect.poll(() => page.evaluate(() => (
    document.getAnimations().filter((animation) => {
      const target = (animation.effect as KeyframeEffect | null)?.target;
      return target instanceof Element
        && target.closest('[data-agent-role="bgm-director"]');
    }).length
  ))).toBe(0);
});

test("BGM waveform pulse rises and falls while its peak propagates left to right", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.getByRole("button", { name: "BGM Director" }).click();
  await page.getByRole("button", { name: "Idle" }).click();
  await page.getByRole("button", { name: "Working" }).click();
  await page.waitForFunction(() => {
    const pulseAnimations = document.getAnimations().filter((animation) => {
      const target = (animation.effect as KeyframeEffect | null)?.target;
      return target instanceof Element
        && target.matches('[data-part^="waveform-pulse-"]')
        && animation.effect?.getTiming().iterations === Infinity;
    });
    return pulseAnimations.length === 5;
  }, undefined, { timeout: 2_000 });

  const samples = await page.evaluate(async () => {
    const parts = [
      "waveform-pulse-1",
      "waveform-pulse-2",
      "waveform-pulse-3",
      "waveform-pulse-4",
      "waveform-pulse-5",
    ];
    const animations = parts.map((part) => document.getAnimations().find((candidate) => {
      const target = (candidate.effect as KeyframeEffect | null)?.target;
      return target instanceof Element && target.matches(`[data-part="${part}"]`);
    }));
    if (animations.some((animation) => !animation)) {
      throw new Error("Missing BGM waveform pulse animation");
    }

    const phaseSamples: number[][] = [];
    for (const time of [0, 625, 1_250, 2_000, 2_500]) {
      for (const animation of animations) {
        animation!.pause();
        animation!.currentTime = time;
      }
      await new Promise(requestAnimationFrame);
      phaseSamples.push(animations.map((animation) => {
        const target = (animation!.effect as KeyframeEffect).target;
        if (!(target instanceof Element)) {
          throw new Error("Missing BGM waveform pulse target");
        }
        return new DOMMatrixReadOnly(getComputedStyle(target).transform).d;
      }));
    }
    return phaseSamples;
  });

  const peakOwners = samples.map((phase) => phase.indexOf(Math.max(...phase)));
  expect(peakOwners).toEqual([0, 1, 2, 3, 4]);
  for (let pulseIndex = 0; pulseIndex < 5; pulseIndex += 1) {
    const pulseScales = samples.map((phase) => phase[pulseIndex]);
    expect(Math.max(...pulseScales) - Math.min(...pulseScales))
      .toBeGreaterThan(0.68);
  }
});

test("World Setting holds a recognizable real-map atlas at rest", async ({ page }) => {
  await page.goto("/tests/browser/agent-role-gallery.html");
  await page.getByRole("button", { name: "World Setting" }).click();
  await page.getByRole("button", { name: "Idle" }).click();

  const artwork = page.locator(
    "[data-gallery-role='world'] .gallery-artwork",
  );
  await expect(artwork.locator('[data-land-atlas="natural-earth-110m"]'))
    .toHaveCount(2);
  await expect(artwork).toHaveScreenshot("world-setting-real-map-idle.png", {
    animations: "disabled",
  });
});

test("Scene Designer builds a line-art set legibly at its production footprint", async ({ page }) => {
  const artwork = await prepareSceneDesigner(page);
  await sizeArtwork(artwork, 32);

  for (const [name, currentTime] of Object.entries(SCENE_FRAME_TIMES)) {
    await freezeSceneDesignerAt(page, currentTime);
    await expect(artwork).toHaveScreenshot(`scene-designer-${name}-32-dpr1.png`, {
      animations: "allow",
    });
  }

  await artwork.evaluate((element) => {
    const svg = element as SVGSVGElement;
    svg.style.removeProperty("width");
    svg.style.removeProperty("height");
    svg.style.removeProperty("overflow");
  });
  await freezeSceneDesignerAt(page, SCENE_FRAME_TIMES.resolved);
  await expect(page.locator('[data-gallery-role="scene"] .gallery-artwork'))
    .toHaveScreenshot("scene-designer-resolved-large.png", {
      animations: "allow",
    });
});

test("Scene Designer remains legible at 32 pixels on a DPR 2 display", async ({ browser }) => {
  const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5197";
  const context = await browser.newContext({
    baseURL,
    deviceScaleFactor: 2,
    viewport: { width: 1_200, height: 900 },
  });
  const page = await context.newPage();

  try {
    const artwork = await prepareSceneDesigner(page);
    await sizeArtwork(artwork, 32);
    await freezeSceneDesignerAt(page, SCENE_FRAME_TIMES.resolved);
    await expect(artwork).toHaveScreenshot("scene-designer-resolved-32-dpr2.png", {
      animations: "allow",
    });
  } finally {
    await context.close();
  }
});
