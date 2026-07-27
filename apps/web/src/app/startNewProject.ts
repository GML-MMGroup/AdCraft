export async function resetNewProjectStorage() {
  const { clearNewProjectStorage } = await import("../projects/newProject");
  clearNewProjectStorage(window.localStorage);
}
