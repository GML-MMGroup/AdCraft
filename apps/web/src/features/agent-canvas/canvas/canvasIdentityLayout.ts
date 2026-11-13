import type { CanvasPositionV2 } from "../../../types-v2.ts";
import type { AgentCanvasLayoutEdge, AgentCanvasLayoutNode } from "./canvasAutoLayout.ts";
import type { CanvasNodeIdentity } from "./canvasNodeIdentity.ts";

const ROW_GAP = 84;

export function canvasIdentityFamilyKey(identity: CanvasNodeIdentity): string {
  return JSON.stringify([identity.family, identity.scope]);
}

/** Keep Dagre's dependency columns, but give persisted creative order priority over crossing reduction. */
export function alignCanvasIdentityLanes(
  nodes: readonly AgentCanvasLayoutNode[],
  edges: readonly AgentCanvasLayoutEdge[],
  positions: Map<string, CanvasPositionV2>,
): void {
  const families = new Map<string, AgentCanvasLayoutNode[]>();
  for (const node of nodes) {
    if (!node.identity) continue;
    const key = canvasIdentityFamilyKey(node.identity);
    const family = families.get(key) ?? [];
    family.push(node);
    families.set(key, family);
  }
  if (!families.size) return;

  const incoming = new Map(nodes.map(node => [node.id, new Set<string>()]));
  const outgoing = new Map(nodes.map(node => [node.id, new Set<string>()]));
  for (const edge of edges) {
    incoming.get(edge.target)!.add(edge.source);
    outgoing.get(edge.source)!.add(edge.target);
  }
  const placed = new Map<string, AgentCanvasLayoutNode>();
  const x = (node: AgentCanvasLayoutNode) => positions.get(node.id)!.x;
  const overlapsX = (a: AgentCanvasLayoutNode, b: AgentCanvasLayoutNode) => (
    x(a) < x(b) + b.size.width && x(b) < x(a) + a.size.width
  );
  const center = (node: AgentCanvasLayoutNode) => positions.get(node.id)!.y + node.size.height / 2;

  // Shift an entire lane together, so collision avoidance cannot separate an image/video pair.
  function placeLane(lane: AgentCanvasLayoutNode[], desiredCenter: number): number {
    let nextCenter = Math.max(desiredCenter, ...lane.map(node => node.size.height / 2));
    let previousCenter: number;
    do {
      previousCenter = nextCenter;
      for (const node of lane) {
        for (const obstacle of placed.values()) {
          if (!overlapsX(node, obstacle)) continue;
          const clearance = (node.size.height + obstacle.size.height) / 2 + ROW_GAP;
          const obstacleCenter = center(obstacle);
          if (Math.abs(nextCenter - obstacleCenter) < clearance) {
            nextCenter = obstacleCenter + clearance;
          }
        }
      }
    } while (nextCenter > previousCenter);
    for (const node of lane) {
      positions.set(node.id, { x: x(node), y: nextCenter - node.size.height / 2 });
      placed.set(node.id, node);
    }
    return nextCenter;
  }

  const sortedFamilies = [...families.entries()].sort(([keyA, a], [keyB, b]) => (
    Math.min(...a.map(x)) - Math.min(...b.map(x)) || keyA.localeCompare(keyB)
  ));
  const familyBottoms = new Map<CanvasNodeIdentity["family"], number>();
  for (const [, family] of sortedFamilies) {
    const identities = new Map<string, AgentCanvasLayoutNode[]>();
    for (const node of family) {
      const key = node.identity!.key;
      const members = identities.get(key) ?? [];
      members.push(node);
      identities.set(key, members);
    }
    const ordered = [...identities.entries()].sort(([keyA, a], [keyB, b]) => (
      a[0]!.identity!.number - b[0]!.identity!.number || keyA.localeCompare(keyB)
    ));
    const kind = family[0]!.identity!.family;
    let nextTop = familyBottoms.get(kind) ?? 0;
    for (const [, members] of ordered) {
      const lanes: AgentCanvasLayoutNode[][] = [];
      for (const node of members.sort((a, b) => x(a) - x(b) || a.id.localeCompare(b.id))) {
        // Duplicate variants in the same column get separate rows. Prefer a row
        // containing the variant's actual input when more than one row is free.
        const compatible = lanes.filter(lane => lane.every(member => !overlapsX(node, member)));
        const lane = compatible.find(row => row.some(member => incoming.get(node.id)!.has(member.id)))
          ?? compatible[0];
        if (lane) lane.push(node);
        else lanes.push([node]);
      }
      for (const lane of lanes) {
        const height = Math.max(...lane.map(node => node.size.height));
        nextTop = placeLane(lane, nextTop + height / 2) + height / 2 + ROW_GAP;
      }
    }
    // Separate different documents of the same family, even across different columns.
    familyBottoms.set(kind, nextTop);
  }

  // Place unnumbered inputs/outputs near their already arranged neighbors. Grow
  // outward from the numbered lanes so editing/export nodes follow their inputs.
  const remaining = nodes.filter(node => !placed.has(node.id)).sort((a, b) => (
    x(a) - x(b) || center(a) - center(b) || a.id.localeCompare(b.id)
  ));
  const placedNeighbors = (ids: ReadonlySet<string>) => [...ids].flatMap(id => {
    const node = placed.get(id);
    return node ? [node] : [];
  });
  while (remaining.length) {
    const readyIndex = remaining.findIndex(node => (
      placedNeighbors(incoming.get(node.id)!).length || placedNeighbors(outgoing.get(node.id)!).length
    ));
    const [node] = remaining.splice(Math.max(0, readyIndex), 1);
    const predecessors = placedNeighbors(incoming.get(node!.id)!);
    const neighbors = predecessors.length ? predecessors : placedNeighbors(outgoing.get(node!.id)!);
    const desiredCenter = neighbors.length
      ? neighbors.reduce((sum, neighbor) => sum + center(neighbor), 0) / neighbors.length
      : center(node!);
    placeLane([node!], desiredCenter);
  }
}
