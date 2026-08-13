import React from "react";
import { Icon } from "../Icon";

interface AppTopBarProps {
  navCollapsed: boolean;
  onToggleNav: () => void;
  onStartNewSession: () => void;
  onSearchOpen: () => void;
  onBeginWindowDrag: (e: React.PointerEvent) => void;
  activeTitle: string;
  activeInfo: boolean;
  hasHistory: boolean;
  subtitleParts: string[];
  agent: string;
  railHidden: boolean;
  artifactCount: number;
  onSetRailHidden: (fn: (h: boolean) => boolean) => void;
}

export function AppTopBar({
  navCollapsed,
  onToggleNav,
  onStartNewSession,
  onSearchOpen,
  onBeginWindowDrag,
  activeTitle,
  activeInfo,
  hasHistory,
  subtitleParts,
  agent,
  railHidden,
  artifactCount,
  onSetRailHidden,
}: AppTopBarProps) {
  return (
    <div className="main-topbar">
      <div className="main-topbar-side" onPointerDown={onBeginWindowDrag}>
        {navCollapsed && (
          <div className="flex items-center gap-0.5" onMouseDown={(e) => e.stopPropagation()}>
            <button
              className="topbar-icon-btn nav-reveal-btn"
              onClick={onToggleNav}
              aria-label="Expand sidebar (⌘B)"
              title="Expand sidebar (⌘B)"
            >
              <Icon name="sidebar" size={16} />
            </button>
            <button
              className="topbar-icon-btn"
              onClick={onStartNewSession}
              aria-label="New session"
              title="New session"
            >
              <Icon name="plus" size={16} />
            </button>
            <button
              className="topbar-icon-btn"
              onClick={onSearchOpen}
              aria-label="Search"
              title="Search"
            >
              <Icon name="search" size={16} />
            </button>
          </div>
        )}
      </div>

      <div className="main-title cursor-default" onPointerDown={onBeginWindowDrag}>
        <span
          className={"main-title-text font-semibold text-[14px] text-fg " + (activeInfo ? "" : " title-ghost")}
          title={activeTitle}
        >
          {activeTitle}
        </span>
        {hasHistory && (
          <span className="title-sub text-[11px] text-muted font-mono" data-testid="session-subtitle">
            {subtitleParts.join(" · ")}
          </span>
        )}
      </div>

      <div className="main-topbar-side main-topbar-actions" onPointerDown={onBeginWindowDrag}>
        {agent === "cowork" && railHidden && artifactCount > 0 && (
          <button
            className="topbar-artifacts-btn flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-panel border border-border text-[12px] text-fg hover:bg-bg"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={() => onSetRailHidden(() => false)}
            title="Show files this conversation produced"
          >
            <Icon name="file" size={14} />
            <span>Artifacts</span>
            <span className="topbar-artifacts-count text-[11px] px-1.5 py-0.2 rounded bg-accent/20 text-accent font-semibold">{artifactCount}</span>
          </button>
        )}
        {agent !== "chat" && (
          <button
            className="topbar-icon-btn"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={() => onSetRailHidden((h) => !h)}
            aria-label={railHidden ? "Show side panel" : "Hide side panel"}
            title={railHidden ? "Show side panel" : "Hide side panel"}
          >
            <Icon name="sidebarRight" size={16} />
          </button>
        )}
      </div>
    </div>
  );
}
