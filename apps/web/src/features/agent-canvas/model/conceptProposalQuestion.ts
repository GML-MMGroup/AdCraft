/** Match the guided interaction title built from the proposal's public options.
 * Timeline snapshots retain these titles even after the interaction is closed. */
export function conceptProposalQuestion(options: readonly { title: string }[]): string {
  return Array.from(options.map(option => option.title).join(" / ").trim()).slice(0, 160).join("");
}
