import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Layout } from "../../components/Layout";
import { ModeLaunchContext } from "./ModeLaunchContext";

const ModeSelectionPage = lazy(() => import("../../pages/ModeSelectionPage").then(module => ({ default: module.ModeSelectionPage })));

export function ModeLaunchHost() {
  const location = useLocation();
  const navigate = useNavigate();
  const choosing = location.pathname === "/projects/new";
  const [target, setTarget] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [keyboard, setKeyboard] = useState(false);
  const [slow, setSlow] = useState(false);
  const layer = useRef<HTMLDivElement>(null);
  const frames = useRef<number[]>([]);
  const active = target !== null && location.pathname === target;
  const overlay = choosing || active;
  const finish = useCallback(() => {
    setTarget(null);
    setRevealing(false);
    requestAnimationFrame(() => layer.current?.focus());
  }, []);
  const ready = useCallback(() => {
    if (!active) return;
    frames.current.forEach(cancelAnimationFrame);
    frames.current = [requestAnimationFrame(() => {
      frames.current.push(requestAnimationFrame(() => setRevealing(true)));
    })];
  }, [active]);
  useEffect(() => () => { frames.current.forEach(cancelAnimationFrame); }, [active]);
  useEffect(() => {
    if (!active || !revealing) return;
    // Fade completion normally removes the cover; allow 120ms slack for a missed event.
    const timer = setTimeout(finish, keyboard ? 0 : 520);
    return () => clearTimeout(timer);
  }, [active, revealing, keyboard, finish]);
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => setSlow(true), 15000);
    return () => clearTimeout(timer);
  }, [active]);

  return <ModeLaunchContext.Provider value={{
    begin: (_mode, projectId, fromKeyboard) => {
      const path = `/workflow/${encodeURIComponent(projectId)}`;
      setKeyboard(fromKeyboard);
      setRevealing(false);
      setSlow(false);
      setTarget(path);
      void navigate(path, { replace: true });
    },
    ready, finish, revealing: active && revealing, preparing: active, keyboard,
  }}>
    {!choosing && <div ref={layer} tabIndex={-1} inert={active}>
      <Layout><Suspense fallback={<div className="agent-canvas-state">Opening project…</div>}><Outlet /></Suspense></Layout>
    </div>}
    {overlay && <Suspense fallback={<div className="mode-launch-loading">Opening mode selection…</div>}>
      <ModeSelectionPage />
    </Suspense>}
    {active && slow && !revealing && <div className="mode-launch-recovery" role="status">
      Project created. The canvas is taking longer to open.
      <button type="button" onClick={finish}>Open project</button>
    </div>}
  </ModeLaunchContext.Provider>;
}
