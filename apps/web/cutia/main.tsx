import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";
import { Timeline } from "../vendor/cutia/src/components/editor/panels/timeline";
import { PreviewPanel } from "../vendor/cutia/src/components/editor/panels/preview";
import { PropertiesPanel } from "../vendor/cutia/src/components/editor/panels/properties";
import { MediaView } from "../vendor/cutia/src/components/editor/panels/assets/views/media";
import { TextView } from "../vendor/cutia/src/components/editor/panels/assets/views/text";
import { TransitionsView } from "../vendor/cutia/src/components/editor/panels/assets/views/transitions";
import { ResizablePanel, ResizablePanelGroup, ResizableHandle } from "../vendor/cutia/src/components/ui/resizable";
import { TooltipProvider } from "../vendor/cutia/src/components/ui/tooltip";
import { useEditor } from "../vendor/cutia/src/hooks/use-editor";
import { useEditorActions } from "../vendor/cutia/src/hooks/actions/use-editor-actions";
import { useKeybindingsListener, useKeybindingDisabler } from "../vendor/cutia/src/hooks/use-keybindings";
import { invokeAction } from "../vendor/cutia/src/lib/actions";
import { startBridge } from "./bridge";
import { useTranslation } from "./adapters/i18n";
import "./style.css";

function OutputSettings() {
  const editor = useEditor();
  const settings = editor.project.getActive().settings;
  const { t } = useTranslation();
  return <div className="cutia-output-settings">
    <h3>{t("Output settings")}</h3>
    <label>{t("Resolution")}<select value={`${settings.canvasSize.width}x${settings.canvasSize.height}`} onChange={(event) => {
      const [width, height] = event.currentTarget.value.split("x").map(Number);
      void editor.project.updateSettings({ settings: { canvasSize: { width, height } } });
    }}>{[...new Set([`${settings.canvasSize.width}x${settings.canvasSize.height}`, "1920x1080", "1080x1920", "1080x1080", "1280x720", "720x1280", "3840x2160"])].map((size) => <option key={size}>{size}</option>)}</select></label>
    <label>{t("Frame rate")}<select value={settings.fps} onChange={(event) => void editor.project.updateSettings({ settings: { fps: Number(event.currentTarget.value) } })}>
      {[...new Set([settings.fps, 24, 25, 30, 60])].map((fps) => <option key={fps} value={fps}>{fps} fps</option>)}
    </select></label>
    <label>{t("Background")}<input aria-label={t("Background color")} type="color" value={settings.background.type === "color" ? settings.background.color : "#000000"} onChange={(event) => void editor.project.updateSettings({ settings: { background: { type: "color", color: event.currentTarget.value } } })} /></label>
  </div>;
}

function Workspace({ busy }: { busy: boolean }) {
  useEditorActions(); useKeybindingsListener();
  const { disableKeybindings, enableKeybindings } = useKeybindingDisabler();
  useEffect(() => { if (busy) disableKeybindings(); else enableKeybindings(); }, [busy, disableKeybindings, enableKeybindings]);
  const editor = useEditor();
  const { t } = useTranslation();
  const [tab, setTab] = useState("Media");
  const [mobilePane, setMobilePane] = useState("Preview");
  return <TooltipProvider><div className="cutia-workspace" data-mobile-pane={mobilePane}>
    <nav className="cutia-tools" aria-label={t("Editor tools")}>
      <div>{["Media", "Text", "Transitions", "Output settings"].map((name) => <button type="button" key={name} aria-pressed={tab === name} onClick={() => { setTab(name); setMobilePane("Media"); }}>{t(name)}</button>)}</div>
      <div><button type="button" aria-label={t("Undo")} disabled={!editor.command.canUndo()} onClick={() => invokeAction("undo")}>↶ {t("Undo")}</button><button type="button" aria-label={t("Redo")} disabled={!editor.command.canRedo()} onClick={() => invokeAction("redo")}>↷ {t("Redo")}</button></div>
    </nav>
    <nav className="cutia-mobile-switch" aria-label={t("Editor panels")}>{["Media", "Preview", "Properties"].map((name) => <button type="button" key={name} aria-pressed={mobilePane === name} onClick={() => setMobilePane(name)}>{t(name)}</button>)}</nav>
    <ResizablePanelGroup direction="vertical" className="cutia-layout">
      <ResizablePanel defaultSize={64} minSize={30}>
        <ResizablePanelGroup direction="horizontal" className="cutia-top">
          <ResizablePanel defaultSize={23} minSize={15} className="cutia-media-pane"><div className="panel h-full min-h-0 overflow-hidden rounded-sm border">
            {tab === "Media" ? <MediaView /> : tab === "Text" ? <TextView /> : tab === "Transitions" ? <TransitionsView /> : <OutputSettings />}
          </div></ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={53} minSize={25} className="cutia-preview-pane"><PreviewPanel /></ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={24} minSize={15} className="cutia-properties-pane"><PropertiesPanel /></ResizablePanel>
        </ResizablePanelGroup>
      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel defaultSize={36} minSize={20}><section className="cutia-timeline h-full min-h-0" aria-label={t("Timeline")}><Timeline /></section></ResizablePanel>
    </ResizablePanelGroup>
  </div><Toaster theme="dark" richColors /></TooltipProvider>;
}

function App() {
  const [status, setStatus] = useState({ ready: false, loading: "Loading editor…", busy: false, error: "" });
  useEffect(() => startBridge((patch) => setStatus((current) => ({ ...current, ...patch }))), []);
  return <>
    {status.ready ? <Workspace busy={status.busy} /> : <div className="cutia-loading" role={status.error ? "alert" : "status"}>{status.error || status.loading}</div>}
    {status.busy ? <div className="cutia-render-lock" aria-label="Exporting video" /> : null}
  </>;
}

createRoot(document.getElementById("root")!).render(<App />);
