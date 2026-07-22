import { lazy, Suspense, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import type { RouteName } from "../types";
import { AssetsIcon, FolderIcon, HomeIcon, TrashIcon, TutorialIcon } from "../icons";
import { useApp } from "../AppContextValue";
import {
  V2_AUTHORING_CONFLICT_RESOLVED_EVENT,
  v2AuthoringConflictStore,
  type V2AuthoringConflict,
} from "../api/v2AuthoringConflictStore";

const navItems: Array<{ route: Exclude<RouteName, "api-space">; label: string; icon: ReactNode }> = [
  { route: "home", label: "Home", icon: <HomeIcon /> },
  { route: "projects", label: "Projects", icon: <FolderIcon /> },
  { route: "assets", label: "Assets", icon: <AssetsIcon /> },
  { route: "trash", label: "Trash", icon: <TrashIcon /> },
];

const V2WorkflowRevisionControl = lazy(() => import("./V2WorkflowRevisionControl"));

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const [accountOpen, setAccountOpen] = useState(false);
  const [authoringConflict, setAuthoringConflict] = useState<V2AuthoringConflict | null>(() => v2AuthoringConflictStore.current());
  const [resolvingConflict, setResolvingConflict] = useState(false);
  const { apiOnline, apiMessage, storageWarning } = useApp();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => v2AuthoringConflictStore.subscribe(setAuthoringConflict), []);

  async function resolveConflict(action: "retry" | "discard") {
    if (!authoringConflict) return;
    setResolvingConflict(true);
    try {
      await v2AuthoringConflictStore[action]();
      window.dispatchEvent(new CustomEvent(V2_AUTHORING_CONFLICT_RESOLVED_EVENT, {
        detail: authoringConflict.target,
      }));
    } finally {
      setResolvingConflict(false);
    }
  }

  function closeAccountMenu() {
    setAccountOpen(false);
  }

  function signOutDemo() {
    setAccountOpen(false);
    navigate("/");
  }

  return (
    <>
      <nav className="floating-rail" aria-label="Primary navigation">
        {navItems.map((item) => (
          <NavLink
            key={item.route}
            className={({ isActive }) => `rail-item ${isActive ? "is-active" : ""}`}
            to={routePath(item.route)}
            aria-label={item.label}
            end={item.route === "home"}
          >
            <span className="rail-icon">{item.icon}</span>
            <span className="tooltip">{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="app-shell" id="app">
        <header className="topbar">
          <Link className="brand" to="/" aria-label="AdCraft home" onClick={closeAccountMenu}>
            <picture className="brand-picture">
              <source media="(max-width: 620px)" srcSet="/brand/adcraft-icon.webp" />
              <img className="brand-logo" src="/brand/adcraft-logo-wordmark.webp" alt="AdCraft" />
            </picture>
          </Link>
          <div className={`api-chip ${apiOnline ? "is-online" : apiOnline === false ? "is-offline" : ""}`} title={apiMessage}>
            {apiOnline ? "API ready" : apiOnline === false ? "Demo mode" : "Checking"}
          </div>
          {storageWarning ? (
            <div className="storage-warning" role="alert" title={storageWarning}>
              {storageWarning}
            </div>
          ) : null}
          {authoringConflict ? (
            <div className="authoring-conflict" role="alert">
              <span>{authoringConflict.message} Keep the local draft, then retry or discard it.</span>
              <button type="button" disabled={resolvingConflict} onClick={() => void resolveConflict("retry")}>Retry</button>
              <button type="button" disabled={resolvingConflict} onClick={() => void resolveConflict("discard")}>Discard</button>
            </div>
          ) : null}
          <div className="top-actions">
            {location.pathname.startsWith("/workflow") ? (
              <Suspense fallback={null}><V2WorkflowRevisionControl /></Suspense>
            ) : null}
            <Link className="ghost-btn" to="/?guide=1" onClick={closeAccountMenu}>
              <TutorialIcon />
              <span>Tutorial</span>
            </Link>
            <button
              className="avatar-btn"
              aria-label="Account menu"
              aria-expanded={accountOpen}
              onClick={() => setAccountOpen((value) => !value)}
            >
              A
            </button>
            <div className={`account-menu ${accountOpen ? "is-open" : ""}`}>
              <Link to="/projects" onClick={closeAccountMenu}>All Projects</Link>
              <Link to="/assets" onClick={closeAccountMenu}>My Assets</Link>
              <Link to="/api-space" onClick={closeAccountMenu}>API Space</Link>
              <button type="button" onClick={signOutDemo}>Sign Out</button>
            </div>
          </div>
        </header>

        <main className="main-view" id="view" aria-live="polite" data-route={location.pathname}>
          {children}
        </main>
      </div>
    </>
  );
}

export function PageHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="page-header">
      <h1 className="page-title">{title}</h1>
      <p className="page-subtitle">{subtitle}</p>
    </header>
  );
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <div>
        <div className="mascot" />
        <h3>{text}</h3>
      </div>
    </div>
  );
}

function routePath(route: Exclude<RouteName, "api-space">) {
  if (route === "home") return "/";
  return `/${route}`;
}
