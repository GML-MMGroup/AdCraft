import type { AssetVersionV2 } from "../../../types-v2.ts";

export type StoryboardVideoPreview = {
  src: string;
  poster?: string;
  title: string;
};

export function storyboardVideoPreview(asset: AssetVersionV2 | undefined, title: string): StoryboardVideoPreview | null {
  if (!asset || asset.media_type !== "video") return null;
  const src = asset.public_url || asset.proxy_path || asset.file_path || "";
  if (!src) return null;
  return {
    src,
    poster: asset.thumbnail_path || undefined,
    title,
  };
}
