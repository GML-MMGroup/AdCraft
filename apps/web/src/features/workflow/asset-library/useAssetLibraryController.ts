export function useAssetLibraryController() {
  async function saveAssetLibraryTarget() {
    return null;
  }
  return {
    saveAssetLibraryTarget,
    assetLibrarySaveTarget: null,
    setAssetLibrarySaveTarget: () => undefined,
  };
}
