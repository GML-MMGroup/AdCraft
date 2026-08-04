export async function deleteCanvasEntities(
  ids: string[],
  remove: (id: string) => Promise<void>,
  recover: () => Promise<void>,
): Promise<void> {
  try {
    await Promise.all(ids.map((id) => remove(id)));
  } catch (error) {
    try {
      await recover();
    } catch {
      // Preserve the original mutation error; the caller already exposes it.
    }
    throw error;
  }
}
