import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type { AdRequest } from "../../../types";

type StateSetter<T> = Dispatch<SetStateAction<T>>;

export type WorkflowRunSettingsState = {
  force_rerun: boolean;
  only_missing: boolean;
  run_downstream: boolean;
  download_media: boolean;
  compose_when_ready: boolean;
};

export type WorkflowPromptPanelState = {
  workflowPrompt: string;
  adRequest: AdRequest;
  runSettings: WorkflowRunSettingsState;
  overridePrompt: string;
};

export type WorkflowPromptPanelActions = {
  setWorkflowPrompt: StateSetter<string>;
  setAdRequest: StateSetter<AdRequest>;
  setRunSettings: StateSetter<WorkflowRunSettingsState>;
  setOverridePrompt: StateSetter<string>;
};

export function useWorkflowPromptPanelState(defaultAdRequest: AdRequest): {
  state: WorkflowPromptPanelState;
  actions: WorkflowPromptPanelActions;
} {
  const [workflowPrompt, setWorkflowPrompt] = useState(
    "Create a 30 second summer lemon tea product ad for young office workers.",
  );
  const [adRequest, setAdRequest] = useState<AdRequest>(defaultAdRequest);
  const [runSettings, setRunSettings] = useState<WorkflowRunSettingsState>({
    force_rerun: false,
    only_missing: true,
    run_downstream: false,
    download_media: true,
    compose_when_ready: true,
  });
  const [overridePrompt, setOverridePrompt] = useState("");

  const state = useMemo<WorkflowPromptPanelState>(() => ({
    workflowPrompt,
    adRequest,
    runSettings,
    overridePrompt,
  }), [adRequest, overridePrompt, runSettings, workflowPrompt]);

  const actions = useMemo<WorkflowPromptPanelActions>(() => ({
    setWorkflowPrompt,
    setAdRequest,
    setRunSettings,
    setOverridePrompt,
  }), []);

  return { state, actions };
}
