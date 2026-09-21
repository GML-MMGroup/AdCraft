import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { AgentCanvasStyleSelector } from "../chat/AgentCanvasStyleSelector.tsx";
import type { BrandCreativeMethod, BrandDecisionPanelV1, BrandSkillIdentity } from "./brandDecisions.ts";
import "./brand-skill-picker.css";

function selectionFrom(panel: BrandDecisionPanelV1) {
  const selected = panel.skill_stack?.entries.filter((entry) => entry.selected && entry.version) ?? [];
  return {
    methods: selected.filter((entry) => entry.skill_kind === "creative_method")
      .map((entry) => ({ skill_id: entry.skill_id, version: entry.version! })),
    style: selected.find((entry) => entry.skill_kind === "audiovisual_style") ?? null,
  };
}

export function BrandSkillPicker({ decisions, responseLocale, onClose, onUpdated, onConversationRefresh }: {
  decisions: BrandDecisionPanelV1;
  responseLocale: string;
  onClose: () => void;
  onUpdated: (panel: BrandDecisionPanelV1) => void;
  onConversationRefresh: () => Promise<void> | void;
}) {
  const zh = responseLocale.startsWith("zh");
  const [panel, setPanel] = useState(decisions);
  const [catalog, setCatalog] = useState<BrandCreativeMethod[] | null>(null);
  const [methods, setMethods] = useState(() => selectionFrom(decisions).methods);
  const [style, setStyle] = useState<{ skill_id: string; version: string | null; title: string } | null>(() => selectionFrom(decisions).style);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [continuePending, setContinuePending] = useState(false);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    mounted.current = true;
    const focusTarget = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onKey = (event: KeyboardEvent) => {
      // The existing style picker can sit above this dialog.
      if (Array.from(document.querySelectorAll('[role="dialog"]')).at(-1) !== dialogRef.current) return;
      if (event.key === "Escape" && !inFlight.current) closeRef.current();
      if (event.key !== "Tab") return;
      const controls = dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]');
      const first = controls?.[0];
      const last = controls?.[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      mounted.current = false;
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
      if (focusTarget?.isConnected) focusTarget.focus();
    };
  }, []);

  async function loadCatalog() {
    try {
      const response = await agentCanvasApi.brandCreativeMethodSkills();
      if (mounted.current) setCatalog(response.items);
    } catch {
      if (mounted.current) setError(zh ? "创意方法加载失败，请重试。" : "Creative methods could not be loaded. Retry.");
    }
  }

  useEffect(() => {
    let cancelled = false;
    agentCanvasApi.brandCreativeMethodSkills().then((response) => {
      if (!cancelled) setCatalog(response.items);
    }).catch(() => {
      if (!cancelled) setError(zh ? "创意方法加载失败，请重试。" : "Creative methods could not be loaded. Retry.");
    });
    return () => { cancelled = true; };
  }, [zh]);

  function replacePanel(next: BrandDecisionPanelV1) {
    setPanel(next);
    const selection = selectionFrom(next);
    setMethods(selection.methods);
    setStyle(selection.style);
    onUpdated(next);
  }

  useEffect(() => {
    if (decisions.journey.stage_revision <= panel.journey.stage_revision) return;
    setPanel(decisions);
    const selection = selectionFrom(decisions);
    setMethods(selection.methods);
    setStyle(selection.style);
    setNotice(zh ? "选择已更新，请检查最新组合。" : "The selection changed. Review the latest combination.");
  }, [decisions, panel.journey.stage_revision, zh]);

  async function refreshPanel() {
    setNeedsRefresh(true);
    const next = await agentCanvasApi.brandDecisions(panel.workflow_id);
    if (!mounted.current) return;
    replacePanel(next);
    await onConversationRefresh();
    if (mounted.current) setNeedsRefresh(false);
    return next;
  }

  async function continueJourney() {
    await agentCanvasApi.brandNextQuestion(panel.workflow_id);
    if (!mounted.current) return;
    await refreshPanel();
    if (mounted.current) onClose();
  }

  const editable = panel.journey.stage === "skill-stack" && panel.open_card?.stage === "skill-stack"
    && panel.open_card.stage_revision === panel.journey.stage_revision;
  const valid = Boolean(catalog && methods.length > 0 && methods.length <= 7 && style?.version
    && methods.every((method) => catalog.some((entry) => entry.skill_id === method.skill_id && entry.version === method.version)));

  async function submit(confirm: boolean) {
    if (inFlight.current || !editable || !valid || !style?.version || !panel.open_card || needsRefresh) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    setNotice(null);
    let committed = false;
    try {
      const next = await agentCanvasApi.brandSelectSkills(panel.workflow_id, {
        card_id: panel.open_card.card_id,
        expected_stage_revision: panel.journey.stage_revision,
        creative_methods: methods,
        audiovisual_style: { skill_id: style.skill_id, version: style.version },
        confirm,
      });
      committed = true;
      if (!mounted.current) return;
      replacePanel(next);
      if (confirm) {
        setContinuePending(true);
        await continueJourney();
      } else {
        setNotice(zh ? "已保存，尚未激活或进入下一阶段。" : "Saved. No style activated or stage advanced.");
        await onConversationRefresh();
      }
    } catch (failure) {
      if (!mounted.current) return;
      if (!committed && isV2ApiError(failure) && failure.status === 409) {
        try {
          const latest = await refreshPanel();
          if (mounted.current && confirm && latest?.journey.stage === "treatment" && !latest.open_card) setContinuePending(true);
        } catch { /* Keep submissions blocked until refresh succeeds. */ }
        if (mounted.current) setError(zh ? "当前卡片已更新，请重新加载并检查最新选择。" : "The card changed. Reload and review the latest selection.");
      } else if (!committed && isV2ApiError(failure) && failure.status === 422) {
        await loadCatalog();
        if (mounted.current) setError(zh ? "Skill 或版本已失效，请从目录重新选择。" : "A Skill or version is invalid. Select it again from the catalog.");
      } else {
        if (committed && !confirm) setNeedsRefresh(true);
        setError(committed
          ? (zh ? "选择已保存，但后续刷新失败。请重试下一步，不要重复确认。" : "Selection saved, but continuation failed. Retry the next step without confirming again.")
          : (zh ? "保存失败，请检查连接后重试。" : "Could not save. Check the connection and retry."));
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }

  async function retry() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    try {
      if (continuePending) await continueJourney();
      else if (needsRefresh) await refreshPanel();
      else await loadCatalog();
    } catch {
      if (mounted.current) setError(zh ? "暂时无法继续，请稍后重试。" : "Unable to continue. Please retry.");
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }

  function toggleMethod(method: BrandSkillIdentity) {
    setMethods((current) => current.some((item) => item.skill_id === method.skill_id && item.version === method.version)
      ? current.filter((item) => item.skill_id !== method.skill_id)
      : [...current.filter((item) => item.skill_id !== method.skill_id), { skill_id: method.skill_id, version: method.version }]);
  }

  return createPortal(
    <div className="brand-skill-picker-overlay">
      <section ref={dialogRef} className="brand-skill-picker" role="dialog" aria-modal="true" aria-label={zh ? "选择品牌 Skills" : "Choose brand Skills"}>
        <header><h2>{zh ? "选择品牌 Skills" : "Choose brand Skills"}</h2><button type="button" disabled={pending} onClick={onClose}>{zh ? "取消" : "Cancel"}</button></header>
        <p>{zh ? "创意方法可多选，视听风格只选一个。确认后进入创意方案。" : "Choose one or more creative methods and one audiovisual style. Confirm to enter Treatment."}</p>
        {error ? <p role="alert">{error}</p> : null}
        {notice ? <p role="status">{notice}</p> : null}
        {(!catalog || needsRefresh || continuePending) ? <button type="button" disabled={pending} onClick={() => void retry()}>{continuePending ? (zh ? "重试下一步" : "Retry next step") : (zh ? "重新加载" : "Reload")}</button> : null}
        {!editable && !continuePending ? <p>{zh ? "当前阶段不可修改 Skills。" : "Skills cannot be edited at the current stage."}</p> : null}
        <fieldset disabled={pending || !editable || needsRefresh}>
          <legend>{zh ? "创意方法（多选）" : "Creative methods (multiple)"}</legend>
          {!catalog ? <p role="status">{zh ? "正在加载创意方法…" : "Loading creative methods…"}</p> : null}
          {catalog?.map((method) => {
            const entry = panel.skill_stack?.entries.find((item) => item.skill_kind === "creative_method" && item.skill_id === method.skill_id && item.version === method.version);
            return <label key={`${method.skill_id}@${method.version}`} className="brand-skill-picker__choice">
              <input type="checkbox" checked={methods.some((item) => item.skill_id === method.skill_id && item.version === method.version)} onChange={() => toggleMethod(method)} />
              <span><strong>{method.title}</strong><small>{method.summary}</small>{entry?.reason ? <small className="brand-skill-picker__reason">{entry.reason}</small> : null}</span>
            </label>;
          })}
        </fieldset>
        <fieldset disabled={pending || !editable || needsRefresh}>
          <legend>{zh ? "视听风格（单选）" : "Audiovisual style (one)"}</legend>
          {panel.skill_stack?.entries.filter((entry) => entry.skill_kind === "audiovisual_style").map((entry) => (
            <label key={`${entry.skill_id}@${entry.version}`} className="brand-skill-picker__choice">
              <input type="radio" name="brand-style" disabled={!entry.version} checked={style?.skill_id === entry.skill_id && style.version === entry.version} onChange={() => setStyle(entry)} />
              <span><strong>{entry.title}</strong>{entry.reason ? <small className="brand-skill-picker__reason">{entry.reason}</small> : null}</span>
            </label>
          ))}
          <p>{zh ? "当前选择：" : "Current selection: "}{style?.title ?? (zh ? "请从目录选择" : "Choose from the catalog")}</p>
          <AgentCanvasStyleSelector workflowId={panel.workflow_id} activeStyle={null} onWorkflowRefresh={() => {}}
            responseLocale={responseLocale} triggerLabel={zh ? "选择视听风格" : "Choose audiovisual style"}
            draftSelection={{ selected: style?.version ? { skill_id: style.skill_id, version: style.version } : null, onSelect: setStyle }} />
        </fieldset>
        <footer>
          <button type="button" disabled={pending || !editable || !valid || needsRefresh} onClick={() => void submit(false)}>{pending ? (zh ? "正在保存…" : "Saving…") : (zh ? "保存" : "Save")}</button>
          <button type="button" disabled={pending || !editable || !valid || needsRefresh} onClick={() => void submit(true)}>{zh ? "确认并继续" : "Confirm and continue"}</button>
        </footer>
      </section>
    </div>, document.body,
  );
}
