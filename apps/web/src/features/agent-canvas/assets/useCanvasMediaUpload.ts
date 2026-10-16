import { useLayoutEffect, useRef, useState, type ChangeEvent } from "react";

import type { CanvasPositionV2 } from "../../../types-v2.ts";
import { toProjectAssetBrowserItem, toSourceNodeSelection, type AgentAssetSourceNodeSelection } from "./assetSelection.ts";
import { useAgentCanvasAssets } from "./useAgentCanvasAssets.ts";

interface CanvasMediaUploadOptions {
  workflowId?: string;
  createSourceNode: (selection: AgentAssetSourceNodeSelection, position: CanvasPositionV2) => Promise<void>;
}

/** One local file becomes one ready source node, using the Assets upload/Add node path. */
export function useCanvasMediaUpload({ workflowId, createSourceNode }: CanvasMediaUploadOptions) {
  const inputRef = useRef<HTMLInputElement>(null);
  const targetRef = useRef<CanvasPositionV2 | null>(null);
  const busyRef = useRef(false);
  const generationRef = useRef(0);
  const createSourceNodeRef = useRef(createSourceNode);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { uploadFiles } = useAgentCanvasAssets({ workflowId, scope: "project", enabled: false });

  useLayoutEffect(() => {
    createSourceNodeRef.current = createSourceNode;
  }, [createSourceNode]);

  useLayoutEffect(() => {
    targetRef.current = null;
    busyRef.current = false;
    setUploading(false);
    setError(null);
    return () => { generationRef.current += 1; };
  }, [workflowId]);

  function openPicker(position: CanvasPositionV2) {
    if (!workflowId || busyRef.current) return;
    targetRef.current = position;
    if (inputRef.current) {
      inputRef.current.value = "";
      inputRef.current.click();
    }
  }

  async function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    const position = targetRef.current;
    targetRef.current = null;
    if (!file || !position || !workflowId || busyRef.current) return;
    setError(null);
    if (!/^(image|video)\//i.test(file.type)) {
      setError("Choose an image or video file.");
      return;
    }

    const generation = generationRef.current;
    const isCurrent = () => generationRef.current === generation;
    busyRef.current = true;
    setUploading(true);
    let uploaded = false;
    try {
      const [asset] = await uploadFiles([file]);
      if (!isCurrent()) return;
      uploaded = Boolean(asset);
      const selection = asset ? toSourceNodeSelection(toProjectAssetBrowserItem(asset)) : null;
      if (!selection) throw new Error("The uploaded asset is not ready to use.");
      await createSourceNodeRef.current(selection, position);
    } catch (failure) {
      if (isCurrent()) {
        const detail = failure instanceof Error ? failure.message : "Please try again.";
        setError(uploaded
          ? `Media uploaded, but the node could not be added. Open Project Assets and choose Add node. ${detail}`
          : `Unable to upload media. ${detail}`);
      }
    } finally {
      if (isCurrent()) {
        busyRef.current = false;
        setUploading(false);
      }
    }
  }

  return { inputRef, openPicker, onFileChange, uploading, error, clearError: () => setError(null) };
}
