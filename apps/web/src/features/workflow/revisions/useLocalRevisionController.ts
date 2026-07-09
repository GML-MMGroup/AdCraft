export function useLocalRevisionController() {
  async function startLocalAssetRevision() {
    return null;
  }
  async function pollLocalAssetRevision() {
    return null;
  }
  async function acceptLocalRevisionCandidate() {
    return null;
  }
  async function rejectLocalRevisionCandidate() {
    return null;
  }
  return { startLocalAssetRevision, pollLocalAssetRevision, acceptLocalRevisionCandidate, rejectLocalRevisionCandidate };
}
