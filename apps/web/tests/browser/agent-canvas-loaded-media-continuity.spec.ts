import { expect, test } from "@playwright/test";

const onePixelPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

test("keeps a loaded canvas rendition available across rerenders and remounts", async ({ page }) => {
  const requests = new Map<string, number>();
  await page.route("**/api/v2/assets/asset-continuity/preview**", async (route) => {
    const version = new URL(route.request().url()).searchParams.get("v") ?? "missing";
    requests.set(version, (requests.get(version) ?? 0) + 1);
    await route.fulfill({ status: 200, contentType: "image/png", body: onePixelPng });
  });
  await page.route("**/api/v2/assets/asset-video-continuity/poster**", async (route) => {
    const version = new URL(route.request().url()).searchParams.get("v") ?? "missing";
    requests.set(version, (requests.get(version) ?? 0) + 1);
    await route.fulfill({ status: 200, contentType: "image/png", body: onePixelPng });
  });

  await page.goto("/tests/browser/canvas-loaded-media-continuity-mock.html");
  const preview = page.getByRole("img", { name: "Canvas continuity preview" });
  await expect(preview).toHaveAttribute("src", /^blob:/);
  expect(requests.get("version-1")).toBe(1);
  expect(requests.get("version-video-1")).toBe(1);

  await page.getByRole("button", { name: "Runtime rerender" }).click();
  await page.getByRole("button", { name: "Unmount" }).click();
  await expect(page.getByTestId("unmounted")).toBeVisible();
  await page.getByRole("button", { name: "Remount" }).click();
  await expect(preview).toHaveAttribute("src", /^blob:/);
  expect(requests.get("version-1")).toBe(1);
  expect(requests.get("version-video-1")).toBe(1);

  await page.reload();
  await expect(page.getByRole("img", { name: "Canvas continuity preview" })).toHaveAttribute("src", /^blob:/);
  expect(requests.get("version-1")).toBe(1);
  expect(requests.get("version-video-1")).toBe(1);

  await page.getByRole("button", { name: "AssetVersion v2" }).click();
  await expect(page.getByTestId("canvas-node")).toHaveAttribute("data-canonical-source", /version-2/);
  await expect(page.getByRole("img", { name: "Canvas continuity preview" })).toHaveAttribute("src", /^blob:/);
  expect(requests.get("version-2")).toBe(1);
});
