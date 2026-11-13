import { useUiLocale } from "../../../i18n/locale";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { agentCanvasApi, isV2ApiError } from "../../../api/agentCanvasApi.ts";
import { CloseIcon } from "../../../icons.tsx";
import type { VideoSkillCatalogResponseV2 } from "../../../types-v2.ts";
import { loadVideoSkillCatalog } from "../skills/loadVideoSkillCatalog.ts";
import { BrandSkillGallery, type BrandStyleSelection } from "./BrandSkillGallery.tsx";
import "../chat/agent-canvas-chat.css";
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

export function BrandSkillPicker({ decisions, responseLocale, open = true, onClose, onUpdated, onConfirmed, onConversationRefresh }: {
  decisions: BrandDecisionPanelV1;
  responseLocale: string;
  open?: boolean;
  onClose: () => void;
  onUpdated: (panel: BrandDecisionPanelV1) => void;
  onConfirmed?: (panel: BrandDecisionPanelV1) => void;
  onConversationRefresh: () => Promise<void> | void;
}) {
  const locale = useUiLocale(responseLocale);
  const zh = locale.startsWith("zh");
  const [panel, setPanel] = useState(decisions);
  const [catalog, setCatalog] = useState<BrandCreativeMethod[] | null>(null);
  const [styleCatalog, setStyleCatalog] = useState<VideoSkillCatalogResponseV2 | null>(null);
  const [catalogStatus, setCatalogStatus] = useState<"loading" | "ready" | "error">("loading");
  const catalogRequest = useRef(0);
  const [methods, setMethods] = useState(() => selectionFrom(decisions).methods);
  const [style, setStyle] = useState<BrandStyleSelection | null>(() => selectionFrom(decisions).style);
  const [pendingAction, setPendingAction] = useState<"save" | "confirm" | "generate" | "refresh" | "catalog" | null>(null);
  const pending = pendingAction !== null;
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [continuation, setContinuation] = useState<"generate" | "refresh" | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const confirmedRef = useRef(onConfirmed);
  confirmedRef.current = onConfirmed;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!open) return;
    const focusTarget = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (Array.from(document.querySelectorAll('[role="dialog"]')).at(-1) !== dialogRef.current) return;
      if (event.key === "Escape") closeRef.current();
      if (event.key !== "Tab") return;
      const controls = dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]');
      const first = controls?.[0];
      const last = controls?.[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
      if (focusTarget?.isConnected) focusTarget.focus();
    };
  }, [open]);

  const loadCatalog = useCallback(async () => {
    const request = ++catalogRequest.current;
    setCatalogStatus("loading");
    try {
      const [response, styles] = await Promise.all([agentCanvasApi.brandCreativeMethodSkills(), loadVideoSkillCatalog()]);
      if (mounted.current && request === catalogRequest.current) {
        setCatalog(response.items);
        setStyleCatalog(styles);
        setCatalogStatus("ready");
      }
    } catch {
      if (mounted.current && request === catalogRequest.current) setCatalogStatus("error");
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void loadCatalog();
    return () => { catalogRequest.current += 1; };
  }, [open, loadCatalog]);

  function replacePanel(next: BrandDecisionPanelV1) {
    setPanel(next);
    const selection = selectionFrom(next);
    setMethods(selection.methods);
    setStyle(selection.style);
    onUpdated(next);
  }

  useEffect(() => {
    const newerRevision = decisions.journey.stage_revision > panel.journey.stage_revision;
    // Publishing the recommendation card does not advance the stage revision.
    const cardArrived = decisions.journey.stage_revision === panel.journey.stage_revision
      && decisions.journey.stage === panel.journey.stage
      && !panel.open_card
      && decisions.open_card?.stage === decisions.journey.stage
      && decisions.open_card.stage_revision === decisions.journey.stage_revision;
    if (!newerRevision && !cardArrived) return;
    setPanel(decisions);
    const selection = selectionFrom(decisions);
    setMethods(selection.methods);
    setStyle(selection.style);
    if (!sent && ["skill-stack", "skill-stack-early"].includes(panel.journey.stage)
      && decisions.journey.stage === panel.journey.stage) {
      setNotice(zh ? "选择已更新，请检查最新组合。" : "The selection changed. Review the latest combination.");
    }
  }, [decisions, panel.journey.stage, panel.journey.stage_revision, panel.open_card, sent, zh]);

  async function refreshPanel() {
    setPendingAction("refresh");
    setNeedsRefresh(true);
    const next = await agentCanvasApi.brandDecisions(panel.workflow_id);
    if (!mounted.current) return;
    replacePanel(next);
    await onConversationRefresh();
    if (mounted.current) setNeedsRefresh(false);
    return next;
  }

  async function continueJourney() {
    if (continuation !== "refresh") {
      if (mounted.current) setPendingAction("generate");
      await agentCanvasApi.brandNextQuestion(panel.workflow_id);
      if (!mounted.current) return;
      // Once generation succeeds, recovery must only repeat the reads.
      setContinuation("refresh");
    }
    await refreshPanel();
    if (mounted.current) setContinuation(null);
  }

  const editable = ["skill-stack", "skill-stack-early"].includes(panel.journey.stage) && panel.open_card?.stage === panel.journey.stage
    && panel.open_card.stage_revision === panel.journey.stage_revision;
  const waitingForRecommendations = ["skill-stack", "skill-stack-early"].includes(panel.journey.stage) && (!editable || !panel.skill_stack);
  const catalogReady = catalogStatus === "ready" && Boolean(catalog?.length && styleCatalog?.items.length);
  const choicesReady = catalogReady && !waitingForRecommendations;
  const catalogProblem = catalogStatus === "error"
    ? (zh ? "技能加载失败，请重试。" : "Skills could not be loaded. Retry.")
    : catalogStatus === "ready" && !catalog?.length
      ? (zh ? "暂无可选创意方法，请重新加载。" : "No creative methods are available. Reload to try again.")
      : catalogStatus === "ready" && !styleCatalog?.items.length
        ? (zh ? "暂无可选视听风格，请重新加载。" : "No audiovisual styles are available. Reload to try again.")
        : null;
  const valid = Boolean(choicesReady && catalog && methods.length > 0 && methods.length <= 7 && style?.version
    && styleCatalog?.items.some((entry) => entry.skill_id === style.skill_id && entry.version === style.version)
    && methods.every((method) => catalog.some((entry) => entry.skill_id === method.skill_id && entry.version === method.version)));

  async function submit(confirm: boolean) {
    if (inFlight.current || sent || !editable || !valid || !style?.version || !panel.open_card || needsRefresh) return;
    inFlight.current = true;
    setPendingAction(confirm ? "confirm" : "save");
    setError(null);
    setSent(confirm);
    setNotice(confirm ? (zh ? "方案已发送" : "Proposal sent") : null);
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
      if (mounted.current) replacePanel(next);
      if (confirm) {
        if (mounted.current) {
          setContinuation("generate");
          // Confirmation is durable now; the next question can finish in the background.
          confirmedRef.current?.(next);
        }
        await continueJourney();
      } else if (mounted.current) {
        setNotice(zh ? "已保存，尚未激活或进入下一阶段。" : "Saved. No style activated or stage advanced.");
        setPendingAction("refresh");
        await onConversationRefresh();
      }
    } catch (failure) {
      if (!mounted.current) return;
      if (!committed) {
        setSent(false);
        setNotice(null);
      }
      if (!committed && isV2ApiError(failure) && failure.status === 409) {
        try {
          const latest = await refreshPanel();
          if (mounted.current && confirm && (latest?.journey.stage === "treatment" || latest?.journey.stage === "hypothesis")) {
            setContinuation(latest.open_card ? "refresh" : "generate");
          }
        } catch { /* Keep submissions blocked until refresh succeeds. */ }
        if (mounted.current) setError(zh ? "当前卡片已更新，请重新加载并检查最新选择。" : "The card changed. Reload and review the latest selection.");
      } else if (!committed && isV2ApiError(failure) && failure.status === 422) {
        await loadCatalog();
        if (mounted.current) setError(zh ? "Skill 或版本已失效，请从目录重新选择。" : "A Skill or version is invalid. Select it again from the catalog.");
      } else {
        if (committed && !confirm) setNeedsRefresh(true);
        setError(committed
          ? (zh ? "选择已保存，但后续处理未完成。请使用重试按钮，无需重复确认。" : "Selection saved, but continuation did not finish. Use the retry button without confirming again.")
          : (zh ? "保存失败，请检查连接后重试。" : "Could not save. Check the connection and retry."));
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setPendingAction(null);
    }
  }

  async function retry() {
    if (inFlight.current) return;
    inFlight.current = true;
    setPendingAction(continuation || needsRefresh ? "refresh" : "catalog");
    setError(null);
    try {
      if (continuation) await continueJourney();
      else if (needsRefresh) await refreshPanel();
      else await loadCatalog();
    } catch {
      if (mounted.current) setError(zh ? "暂时无法继续，请稍后重试。" : "Unable to continue. Please retry.");
    } finally {
      inFlight.current = false;
      if (mounted.current) setPendingAction(null);
    }
  }

  function toggleMethod(method: BrandSkillIdentity) {
    setMethods((current) => current.some((item) => item.skill_id === method.skill_id && item.version === method.version)
      ? current.filter((item) => item.skill_id !== method.skill_id)
      : current.length < 7 ? [...current.filter((item) => item.skill_id !== method.skill_id), { skill_id: method.skill_id, version: method.version }] : current);
  }

  const progressMessage = pendingAction === "generate"
    ? (zh ? "Skills 已确认，正在生成创意方案的下一道问题，可能需要一些时间，请勿重复提交。" : "Skills confirmed. Generating the next Treatment question. This may take a while; please do not submit again.")
    : pendingAction === "refresh"
      ? (zh ? "正在刷新品牌信息与对话…" : "Refreshing brand details and conversation…")
      : pendingAction === "catalog"
        ? (zh ? "正在加载创意方法…" : "Loading creative methods…")
        : (zh ? "正在保存 Skills 选择…" : "Saving your Skills selection…");
  const confirmLabel = sent ? (zh ? "方案已发送" : "Proposal sent") : (zh ? "保存并发送" : "Save and send");
  const statusMessage = sent ? (zh ? "方案已发送" : "Proposal sent") : pending ? progressMessage : notice;

  if (!open) return null;

  return createPortal(
    <div className="agent-chat__style-overlay brand-skill-picker-overlay">
      <button type="button" className="agent-chat__style-backdrop" tabIndex={-1} aria-label={zh ? "收起技能组合" : "Dismiss Skill combination"} onClick={onClose} />
      <section ref={dialogRef} className="agent-chat__style-menu brand-skill-picker" role="dialog" aria-modal="true" aria-label={zh ? "选择品牌技能" : "Choose brand Skills"}>
        <header className="agent-chat__style-menu-header">
          <h2>{zh ? "技能组合" : "Skill combination"}</h2>
          <button type="button" onClick={onClose} aria-label={pending || sent ? (zh ? "关闭" : "Close") : (zh ? "取消" : "Cancel")}><CloseIcon /></button>
        </header>
        <div className="brand-skill-picker__feedback">
          {error ? <p role="alert">{error}</p> : null}
          {statusMessage && !error && (choicesReady || sent) ? <p role="status">{statusMessage}</p> : null}
          {sent && pending ? <p>{zh ? "正在后台处理，你可以关闭面板，也可以留在这里查看。" : "Processing in the background. You can close this panel or stay here."}</p> : null}
          {catalogProblem ? <p role="alert">{catalogProblem}</p> : null}
          {!pending && (catalogProblem || needsRefresh || continuation) ? <button type="button" onClick={() => void retry()}>{continuation === "generate" ? (zh ? "重试下一步" : "Retry next step") : (zh ? "重新加载" : "Reload")}</button> : null}
          {!catalogProblem && !choicesReady && !sent ? <p role="status" aria-live="polite">{catalogStatus === "loading"
            ? (zh ? "正在加载技能，请稍候…" : "Loading Skills. Please wait…")
            : (zh ? "正在准备推荐组合，请稍候…" : "Preparing recommendations. Please wait…")}</p> : null}
          {!editable && !waitingForRecommendations && !continuation ? <p>{zh ? "当前阶段不可修改技能。" : "Skills cannot be edited at the current stage."}</p> : null}
        </div>
        {choicesReady && catalog && styleCatalog ? <>
          <BrandSkillGallery catalog={catalog} styleCatalog={styleCatalog} panel={panel} methods={methods} style={style}
            disabled={pending || sent || !editable || needsRefresh} locale={locale} onToggleMethod={toggleMethod} onSelectStyle={setStyle} />
          <footer className="brand-skill-picker__footer">
            <p>{zh ? `已选 ${style ? 1 : 0} 个视听风格 · ${methods.length} 个创意风格` : `${style ? 1 : 0} audiovisual · ${methods.length} creative Skills selected`}</p>
            <div>
              <button type="button" disabled={pending || sent || !editable || !valid || needsRefresh} onClick={() => void submit(false)}>{pendingAction === "save" ? (zh ? "正在保存…" : "Saving…") : (zh ? "保存" : "Save")}</button>
              <button type="button" className="brand-skill-picker__confirm" disabled={pending || sent || !editable || !valid || needsRefresh} onClick={() => void submit(true)}>{confirmLabel}</button>
            </div>
          </footer>
        </> : null}
      </section>
    </div>, document.body,
  );
}
