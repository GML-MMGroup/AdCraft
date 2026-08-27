import { useEffect, useMemo, useState } from "react";
import type { ProjectV2Summary } from "../types-v2.ts";
import { agentCanvasApi } from "../api/agentCanvasApi.ts";
import { createRequestQueue } from "../collections/requestQueue.ts";
import {
  firstUserMessageFromTimeline,
  goalSummaryFromCreativeSession,
  isPlaceholderProjectName,
  resolveProjectDisplayName,
} from "./projectDisplayName.ts";

const PROJECT_NAME_REQUEST_LIMIT = 4;
const PROJECT_NAME_PROJECT_LIMIT = 36;

export function useProjectDisplayNames(projects: ProjectV2Summary[]): Record<string, string> {
  const candidates = useMemo(
    () => projects
      .filter((project) => isPlaceholderProjectName(project.name))
      .slice(0, PROJECT_NAME_PROJECT_LIMIT),
    [projects],
  );
  const [displayNames, setDisplayNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const queue = createRequestQueue(PROJECT_NAME_REQUEST_LIMIT);
    const controllers = new Set<AbortController>();
    const candidateIds = new Set(candidates.map((project) => project.project_id));

    setDisplayNames((current) => {
      const next = Object.fromEntries(
        Object.entries(current).filter(([projectId]) => candidateIds.has(projectId)),
      );
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });

    for (const project of candidates) {
      const controller = new AbortController();
      controllers.add(controller);
      void queue.schedule(
        () => loadProjectDisplayName(project, controller.signal),
        { signal: controller.signal },
      ).then((displayName) => {
        if (cancelled || !displayName) return;
        setDisplayNames((current) => (
          current[project.project_id] === displayName
            ? current
            : { ...current, [project.project_id]: displayName }
        ));
      }).catch(() => {
        // The project card remains usable with its persisted name when metadata is unavailable.
      }).finally(() => {
        controllers.delete(controller);
      });
    }

    return () => {
      cancelled = true;
      for (const controller of controllers) controller.abort();
    };
  }, [candidates]);

  return displayNames;
}

async function loadProjectDisplayName(project: ProjectV2Summary, signal: AbortSignal): Promise<string> {
  let firstUserMessage: string | null = null;
  try {
    const timeline = await agentCanvasApi.agentCanvasChatTimeline(project.workflow_id, 0, 100, { signal });
    firstUserMessage = firstUserMessageFromTimeline(timeline);
  } catch (error) {
    if (signal.aborted) throw error;
  }

  if (firstUserMessage) {
    return resolveProjectDisplayName({ projectName: project.name, firstUserMessage });
  }

  let goalSummary: string | null = null;
  try {
    const session = await agentCanvasApi.agentCanvasCreativeSession(project.workflow_id, { signal });
    goalSummary = goalSummaryFromCreativeSession(session);
  } catch (error) {
    if (signal.aborted) throw error;
  }

  return resolveProjectDisplayName({
    projectName: project.name,
    firstUserMessage,
    goalSummary,
  });
}
