import { expect } from "vitest";

export function assertRoleArtworkContract(
  container: HTMLElement,
  role: string,
  requiredParts: readonly string[],
): SVGSVGElement {
  const artwork = container.querySelector<SVGSVGElement>(
    `svg[viewBox="0 0 512 512"][aria-hidden="true"][data-agent-role="${role}"]`,
  );

  expect(artwork).not.toBeNull();
  for (const part of requiredParts) {
    expect(
      artwork?.querySelectorAll(`[data-part="${part}"]`),
      `expected exactly one data-part="${part}"`,
    ).toHaveLength(1);
  }

  return artwork as SVGSVGElement;
}
