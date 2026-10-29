export type V2AuthoringResource = "project" | "workflow";

class V2EtagStore {
  private readonly projects = new Map<string, string>();
  private readonly workflows = new Map<string, string>();

  get(resource: V2AuthoringResource, id: string): string | null {
    return (resource === "project" ? this.projects : this.workflows).get(id) ?? null;
  }

  set(resource: V2AuthoringResource, id: string, etag: string | null): void {
    const values = resource === "project" ? this.projects : this.workflows;
    if (etag) {
      // Background reads may arrive out of order; retain the newest canonical revision.
      const revision = (value: string | undefined) => {
        const match = value?.match(/(?:-v|:revision:|-r)(\d+)"?$/);
        return match ? Number(match[1]) : null;
      };
      const incoming = revision(etag);
      const current = revision(values.get(id));
      if (incoming !== null && current !== null && incoming < current) return;
      values.set(id, etag);
    }
    else values.delete(id);
  }

  getProject(projectId: string): string | null {
    return this.get("project", projectId);
  }

  getWorkflow(workflowId: string): string | null {
    return this.get("workflow", workflowId);
  }

  clear(): void {
    this.projects.clear();
    this.workflows.clear();
  }
}

export const v2EtagStore = new V2EtagStore();
