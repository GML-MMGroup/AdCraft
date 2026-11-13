import { agentCanvasApi } from "../../../api/agentCanvasApi.ts";
import type { VideoSkillCatalogResponseV2, VideoSkillCategoryV2, VideoSkillPreviewV2, VideoSkillPublicDetailV2 } from "../../../types-v2.ts";

// Curated replacements shared by the Style picker and companion creative Skills.
const previewOverrides: Readonly<Record<string, VideoSkillPreviewV2>> = {
  "suspense-to-sensory-release@1.0.0": {
    kind: "image",
    media_url: "/imgs/video-skills/suspense-to-sensory-release-v2.webp",
    summary: "A cinematic coffee ritual shifts from cool, restrained suspense to warm, tactile relief.",
  },
  "costume-comedy-live-action@1.0.0": {
    kind: "image",
    media_url: "/imgs/video-skills/costume-comedy-live-action-v2.webp",
    summary: "Real actors in an ornate Chinese period interior turn ceremonial grandeur into playful delight with a small handheld fan.",
  },
};

/** Share pagination and ordering between the Style picker and brand Skill combinations. */
export async function loadVideoSkillCatalog(): Promise<VideoSkillCatalogResponseV2> {
  const categories = new Map<string, VideoSkillCategoryV2>();
  const items = new Map<string, VideoSkillPublicDetailV2>();
  const seenCursors = new Set<string>();
  let cursor: string | null = null;
  let catalogVersion = "unknown";
  do {
    const page = await agentCanvasApi.listVideoSkills({ limit: 100, ...(cursor ? { cursor } : {}) });
    catalogVersion = page.catalog_version;
    page.categories.forEach(category => categories.set(category.category_id, category));
    page.items.forEach(skill => {
      const key = `${skill.skill_id}@${skill.version}`;
      const preview = previewOverrides[key];
      items.set(key, preview ? { ...skill, preview } : skill);
    });
    cursor = page.next_cursor;
    if (cursor && seenCursors.has(cursor)) throw new Error("The Style catalog returned a repeated page cursor.");
    if (cursor) seenCursors.add(cursor);
  } while (cursor);
  return {
    catalog_version: catalogVersion,
    categories: [...categories.values()].sort((a, b) => a.display_order - b.display_order),
    items: [...items.values()].sort((a, b) => a.display_order - b.display_order),
    next_cursor: null,
  };
}
