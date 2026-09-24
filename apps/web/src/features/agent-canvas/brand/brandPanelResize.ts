export function brandPanelMaxWidth(viewport: number, chat: number) {
  return Math.max(260, Math.min(520, viewport - chat - 320));
}
