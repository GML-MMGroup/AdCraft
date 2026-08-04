export type PlanningExpert =
  | "product_designer"
  | "character_designer"
  | "scene_designer"
  | "bgm_director";

export interface AcceptedScript {
  readonly accepted: boolean;
  readonly script_id?: string;
  readonly [key: string]: unknown;
}

export interface ExpertPlan {
  readonly expert: PlanningExpert;
  readonly accepted: boolean;
  readonly [key: string]: unknown;
}

interface PlanningDelegates {
  readonly writeScript: () => Promise<AcceptedScript>;
  readonly planExpert: (expert: PlanningExpert, script: AcceptedScript) => Promise<ExpertPlan>;
}

export class PlanningCoordinator {
  constructor(private readonly delegates: PlanningDelegates) {}

  async createWorkflowPlan(input: {
    readonly experts: ReadonlyArray<PlanningExpert>;
  }): Promise<{
    readonly script: AcceptedScript;
    readonly expert_plans: ReadonlyArray<ExpertPlan>;
  }> {
    const script = await this.delegates.writeScript();
    if (!script.accepted) throw new Error("agent_script_contract_rejected");
    const expertPlans = await Promise.all(
      input.experts.map((expert) => this.delegates.planExpert(expert, script)),
    );
    return { script, expert_plans: expertPlans };
  }
}
