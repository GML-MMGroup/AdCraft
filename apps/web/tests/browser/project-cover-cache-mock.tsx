import { useState } from "react";
import { createRoot } from "react-dom/client";

import { ProjectList, type ProjectListItem } from "../../src/pages/projects/ProjectList.tsx";
import "../../src/styles/base.css";
import "../../src/styles/theme.css";

const baseProject: ProjectListItem = {
  key: "project-cover-cache",
  source: "saved",
  projectId: "project-cover-cache",
  name: "Cached cover project",
  time: "Updated today",
  updatedAt: "2026-08-30T08:00:00Z",
  favorite: false,
  workflowId: "workflow-cover-cache",
  coverAssetId: null,
};

function AcceptanceHarness() {
  const [updatedAt, setUpdatedAt] = useState(baseProject.updatedAt);
  return (
    <main className="project-cover-cache-mock">
      <button type="button" onClick={() => setUpdatedAt("2026-08-30T09:00:00Z")}>
        Refresh cover metadata
      </button>
      <ProjectList
        projects={[{ ...baseProject, updatedAt }]}
        onOpenProject={() => undefined}
        onTrashProject={() => undefined}
        onToggleFavorite={() => undefined}
        onRenameProject={() => undefined}
      />
    </main>
  );
}

const style = document.createElement("style");
style.textContent = `
  html, body, #root { min-height: 100%; margin: 0; background: #08090d; color: #f1f2f6; }
  .project-cover-cache-mock { width: min(100% - 32px, 980px); margin: 24px auto; font-family: Inter, sans-serif; }
  .project-cover-cache-mock > button { margin-bottom: 16px; border: 1px solid #626a7a; border-radius: 6px; padding: 8px 12px; background: #191d26; color: #f1f2f6; }
  .project-list-virtual { min-height: 292px; }
`;
document.head.append(style);

createRoot(document.getElementById("root")!).render(<AcceptanceHarness />);
