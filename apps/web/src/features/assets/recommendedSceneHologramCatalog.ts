const HOLOGRAM_SCENE_CATALOG = {
  "recommended-v1-scene-001": "scene-001-multi-view.png",
  "recommended-v1-scene-002": "scene-002-multi-view.png",
  "recommended-v1-scene-003": "scene-003-multi-view.png",
  "recommended-v1-scene-004": "scene-004-multi-view.png",
  "recommended-v1-scene-005": "scene-005-multi-view.png",
  "recommended-v1-scene-006": "scene-006-multi-view.png",
  "recommended-v1-scene-007": "scene-007-multi-view.png",
  "recommended-v1-scene-008": "scene-008-multi-view.png",
  "recommended-v1-scene-009": "scene-009-multi-view.png",
  "recommended-v1-scene-010": "scene-010-multi-view.png",
  "recommended-v1-scene-011": "scene-011-multi-view.png",
  "recommended-v1-scene-012": "scene-012-multi-view.png",
  "recommended-v1-scene-013": "scene-013-multi-view.png",
  "recommended-v1-scene-014": "scene-014-multi-view.png",
  "recommended-v1-scene-015": "scene-015-multi-view.png",
  "recommended-v1-scene-016": "scene-016-multi-view.png",
  "recommended-v1-scene-017": "scene-017-multi-view.png",
  "recommended-v1-scene-018": "scene-018-multi-view.png",
  "recommended-v1-scene-019": "scene-019-multi-view.png",
  "recommended-v1-scene-020": "scene-020-multi-view.png",
} as const;

export const HOLOGRAM_SCENE_FILENAMES = Object.values(HOLOGRAM_SCENE_CATALOG).sort();

function canonicalEntityId(assetId: string) {
  return assetId.startsWith("recommended:") ? assetId.slice("recommended:".length) : assetId;
}

export function hologramSceneUrlForAsset(assetId: string): string | null {
  const filename = HOLOGRAM_SCENE_CATALOG[
    canonicalEntityId(assetId) as keyof typeof HOLOGRAM_SCENE_CATALOG
  ];
  return filename ? `/assets/hologram/${filename}` : null;
}
