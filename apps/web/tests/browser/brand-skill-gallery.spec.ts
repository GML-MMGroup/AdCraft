import { expect, test } from "@playwright/test";

const url = "/tests/browser/brand-skill-gallery-mock.html";
const preview = { kind: "image", summary: null, media_url: "/tests/skill-gallery-preview.svg" };
const methodIds = ["summer-sensory-use-moment", "collision-montage", ...Array.from({ length: 7 }, (_, index) => `method-${index}`)];
const methods = methodIds.map(skill_id => ({ skill_id, version: "1.0.0", skill_kind: "creative_method", title: skill_id, summary: skill_id }));
const styles = ["japanese-summer-sensory-film", "platform-default", "industrial-product-commercial"].map((skill_id, display_order) => ({ skill_id, version: "1.0.0", title: skill_id === "industrial-product-commercial" ? "工业产品功能广告" : skill_id, summary: "A visual style", category: "test", tags: [], supported_use_cases: [], preview, display_order }));

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("adcraft.locale", "zh-CN");
    window.addEventListener("skill-gallery-preview-save", event => localStorage.setItem("preview-save", JSON.stringify((event as CustomEvent).detail)));
  });
  await page.route("**/tests/skill-gallery-preview.svg", route => route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#5e746c"/></svg>' }));
  await page.route("**/api/v2/brand/creative-method-skills", route => route.fulfill({ json: { items: methods } }));
  await page.route("**/api/v2/video-skills?*", route => route.fulfill({ json: { items: styles, categories: [], catalog_version: "1", next_cursor: null } }));
});

test("combines both catalogs in one dialog and submits the selection edited across all three tabs", async ({ page }) => {
  const writes: string[] = [];
  page.on("request", request => { if (request.method() === "POST") writes.push(request.url()); });
  await page.goto(url);
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(page.getByRole("tab")).toHaveCount(3);
  const chineseStyle = page.locator('[data-skill-id="industrial-product-commercial"]');
  await expect(chineseStyle.locator("strong")).toHaveText("工业产品功能广告");
  await expect(chineseStyle.locator(".agent-chat__style-option-secondary-title")).toHaveText("Industrial Product Commercial");
  await page.getByRole("radio", { name: "platform-default" }).check();
  await page.getByRole("tab", { name: "创意风格 Skill" }).click();
  const companion = page.locator('[data-skill-id="summer-sensory-use-moment"]');
  await expect(companion.locator("strong")).toHaveText("夏日感官使用时刻");
  await expect(companion.locator(".agent-chat__style-option-secondary-title")).toHaveText("summer-sensory-use-moment");
  await expect(companion.locator("img")).toHaveAttribute("src", preview.media_url);
  const generatedPreview = page.locator('[data-skill-id="collision-montage"] img');
  await expect(generatedPreview).toHaveAttribute("src", "/imgs/creative-skills/collision-montage.webp");
  await expect.poll(() => generatedPreview.evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(960);
  await expect(page.locator('[data-skill-id="method-0"]').getByRole("img", { name: "暂无预览" })).toBeVisible();
  await page.getByRole("checkbox", { name: "method-0", exact: true }).check();
  await page.getByRole("tab", { name: /已选 Skill/ }).click();
  await expect(page.getByRole("checkbox")).toHaveCount(4);
  await page.locator('[data-skill-id="collision-montage"] input').click();
  await expect(page.getByRole("checkbox")).toHaveCount(3);
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("preview-save") ?? "null"))).toMatchObject({
    confirm: false,
    creative_methods: [{ skill_id: "summer-sensory-use-moment", version: "1.0.0" }, { skill_id: "method-0", version: "1.0.0" }],
    audiovisual_style: { skill_id: "platform-default", version: "1.0.0" },
  });
  expect(writes).toEqual([]);
});

for (const width of [390, 1440]) {
  test(`keeps controls visible and cards within the dialog at width ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(url);
    for (const name of ["视听风格 Skill", "创意风格 Skill", /已选 Skill/]) {
      await page.getByRole("tab", { name }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      expect(await dialog.evaluate(element => {
        const rect = element.getBoundingClientRect();
        return rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight
          && element.scrollWidth <= element.clientWidth
          && [...element.querySelectorAll('.brand-skill-gallery__card')].every(card => card.scrollWidth <= card.clientWidth);
      })).toBe(true);
      await expect(page.getByRole("button", { name: "保存并发送" })).toBeInViewport();
    }
  });
}

test("supports keyboard tab navigation and restores focus after closing", async ({ page }) => {
  await page.goto(url);
  const stylesTab = page.getByRole("tab", { name: "视听风格 Skill" });
  await stylesTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "创意风格 Skill" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "创意风格 Skill" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "打开技能面板" }).click();
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByRole("button", { name: "打开技能面板" })).toBeFocused();
});

test("an unavailable preview keeps the Skill name and selection usable", async ({ page }) => {
  await page.route("**/tests/skill-gallery-preview.svg", route => route.abort());
  await page.goto(url);
  const card = page.locator('[data-skill-id="platform-default"]');
  await expect(card.getByRole("img", { name: "暂无预览" })).toBeVisible();
  await card.getByRole("radio", { name: "platform-default" }).check();
  await expect(card.getByRole("radio")).toBeChecked();
  await expect(page.getByRole("button", { name: "保存", exact: true })).toBeEnabled();
});
