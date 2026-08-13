import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getPersonas,
  getSettings,
  INBOX_UNLOCK,
  PERSONAS_CHANGED,
  setNavLayout,
  type Persona,
  type RecentWorkspace,
  type SurfaceVisibility,
} from "../api";
import type { SessionInfo } from "../types";
import { isProjectScoped, shortPersonaName } from "../personaScope";
import { Icon, type IconName } from "./Icon";
import { personaGlyph } from "./personaIcon";
import { SearchModal } from "./SearchModal";
import { baseName } from "../paths";
import { showPersonas } from "../flags";
import { AttnBadge, LiveDot } from "./sidebar/SidebarBadges";
import { SessionRow } from "./sidebar/SessionRow";
import { NewSessionSplit } from "./sidebar/NewSessionSplit";
import { useAuth } from "../auth/AuthContext";
import { useNavigate } from "react-router-dom";

const SURFACES: { key: string; label: string; icon: IconName; cls: string }[] = [
  { key: "cowork", label: "Coworker", icon: "diamond", cls: "ico-cowork" },
  { key: "chat", label: "Chat", icon: "chat", cls: "ico-chat" },
  { key: "code", label: "Code", icon: "code", cls: "ico-code" },
];

const surfaceFromPersona = (p: Persona) => ({
  key: p.id,
  label: shortPersonaName(p.name, p.id),
  icon: personaGlyph(p.icon, p.family),
  cls: `ico-${p.icon || "cowork"}`,
});

interface Props {
  agent: string;
  workspace: string;
  surfaces: SurfaceVisibility;
  sessions: SessionInfo[];
  projects: RecentWorkspace[];
  activeSession: string;
  onSwitchAgent: (agent: string) => void;
  onNewSession: (agent: string) => void;
  onSelectSession: (id: string, workspace: string, agent: string) => void;
  onNewProject: (persona: string) => void;
  onRenameSession: (id: string, title: string) => void;
  onDeleteSession: (id: string) => void;
  onArchiveSession: (id: string, archived: boolean) => void;
  onTogglePin: (id: string, pinned: boolean) => void;
  onManage: () => void;
  onOpenPersona: (id: string) => void;
  onManagePersonas: () => void;
  onOpenIntegrations: () => void;
  onOpenAudit: () => void;
  onOpenInbox: () => void;
  integrationsActive: boolean;
  auditActive: boolean;
  inboxActive: boolean;
  collapsed?: boolean;
  onCollapse?: () => void;
  onPeekLeave?: () => void;
}

export function Sidebar(props: Props) {
  const { state: authState, signOut } = useAuth();
  const navigate = useNavigate();
  const [searchModalOpen, setSearchModalOpen] = useState(false);
  const [appMenuOpen, setAppMenuOpen] = useState(false);
  const [inboxUnlocked, setInboxUnlocked] = useState(
    () => localStorage.getItem("ocw:inbox-unlocked") === "1",
  );

  useEffect(() => {
    const unlock = () => {
      localStorage.setItem("ocw:inbox-unlocked", "1");
      setInboxUnlocked(true);
    };
    window.addEventListener(INBOX_UNLOCK, unlock);
    return () => {
      window.removeEventListener(INBOX_UNLOCK, unlock);
    };
  }, []);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmDelId, setConfirmDelId] = useState<string | null>(null);
  const [rowMenu, setRowMenu] = useState<{
    id: string;
    top: number;
    left: number;
    anchor: HTMLElement;
  } | null>(null);

  const closeRowMenu = () => {
    setRowMenu(null);
    setConfirmDelId(null);
  };

  const openRowMenu = (id: string, anchor: HTMLElement) => {
    const r = anchor.getBoundingClientRect();
    const MENU_W = 160;
    const MENU_H = 150;
    setConfirmDelId(null);
    setRowMenu({
      id,
      top: r.bottom + 4 + MENU_H > window.innerHeight ? r.top - MENU_H : r.bottom + 4,
      left: Math.max(8, r.right - MENU_W),
      anchor,
    });
  };

  useEffect(() => {
    if (!rowMenu) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeRowMenu();
    const onScroll = (e: Event) => {
      const t = e.target;
      if (t === document || (t instanceof Node && t.contains(rowMenu.anchor))) closeRowMenu();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [rowMenu]);

  const [showArchived, setShowArchived] = useState(false);
  const [personas, setPersonas] = useState<Persona[] | null>(null);

  useEffect(() => {
    const load = () =>
      getPersonas()
        .then(setPersonas)
        .catch(() => setPersonas(null));
    load();
    window.addEventListener(PERSONAS_CHANGED, load);
    return () => window.removeEventListener(PERSONAS_CHANGED, load);
  }, []);

  const personaOf = (id: string) => personas?.find((p) => p.id === id);

  const defaultLayout: "flat" | "grouped" = showPersonas() ? "grouped" : "flat";
  const [layout, setLayout] = useState<"flat" | "grouped">(defaultLayout);
  const [peek, setPeek] = useState(5);

  useEffect(() => {
    getSettings()
      .then((s) => {
        setLayout(
          s.nav_layout === "flat" ? "flat" : s.nav_layout === "grouped" ? "grouped" : defaultLayout,
        );
        if (s.sessions_peek) setPeek(s.sessions_peek);
      })
      .catch(() => {});
  }, []);

  const setGroupBy = (next: "flat" | "grouped") => {
    setLayout(next);
    setNavLayout(next).catch(() => {});
  };

  const RECENT_PEEK = 4;
  const [recentExpanded, setRecentExpanded] = useState(false);
  const [groupMenuOpen, setGroupMenuOpen] = useState(false);
  const [filterPersonas] = useState<Set<string>>(new Set());



  const personaVisible = (agent: string) =>
    filterPersonas.size === 0 || filterPersonas.has(agent);

  const [openKey, setOpenKey] = useState<string | null>(props.agent);
  useEffect(() => setOpenKey(props.agent), [props.agent]);
  const browseKey = openKey ?? props.agent;

  const [projToggled, setProjToggled] = useState<Set<string>>(new Set());
  const [projShowAll, setProjShowAll] = useState<Set<string>>(new Set());
  const [personaShowAll, setPersonaShowAll] = useState<Set<string>>(new Set());

  const toggleSet = (set: Set<string>, key: string) => {
    const next = new Set(set);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  };

  const pinnedSessions = props.sessions.filter(
    (s) => s.pinned && !s.session_id.startsWith("__") && !s.archived,
  );

  const appMenuItem = (
    icon: IconName,
    label: string,
    onClick: () => void,
    active?: boolean,
    trailing?: ReactNode,
  ) => (
    <button
      className={
        "w-full flex items-center gap-2.5 px-3 py-1.5 text-[13px] text-left " +
        (active ? "text-fg bg-bg" : "hover:bg-bg")
      }
      onClick={() => {
        setAppMenuOpen(false);
        onClick();
      }}
    >
      <Icon name={icon} size={15} className="shrink-0 text-muted" />
      <span className="flex-1">{label}</span>
      {trailing != null && <span aria-hidden>{trailing}</span>}
    </button>
  );



  const attnByPersona = new Map<string, number>();
  const liveByPersona = new Map<string, "working" | "sleeping">();
  let totalAttention = 0;
  for (const s of props.sessions) {
    if (s.session_id.startsWith("__") || s.archived) continue;
    const a = s.attention || 0;
    if (a > 0) {
      attnByPersona.set(s.agent, (attnByPersona.get(s.agent) || 0) + a);
      totalAttention += a;
    }
    if (s.liveness === "working") liveByPersona.set(s.agent, "working");
    else if (s.liveness === "sleeping" && liveByPersona.get(s.agent) !== "working")
      liveByPersona.set(s.agent, "sleeping");
  }

  useEffect(() => {
    if (totalAttention > 0 && !inboxUnlocked) {
      localStorage.setItem("ocw:inbox-unlocked", "1");
      setInboxUnlocked(true);
    }
  }, [totalAttention]);

  const all = props.sessions.filter((s) => s.agent === browseKey && !s.session_id.startsWith("__"));
  const mine = all.filter((s) => !s.archived && !s.pinned);
  const archived = all.filter((s) => s.archived);
  const workspaceSurface = isProjectScoped(personaOf(browseKey));
  const matches = (_s: SessionInfo) => true;

  const recentSessions = [...props.sessions]
    .filter((s) => !s.archived && !s.session_id.startsWith("__") && !s.pinned)
    .filter((s) => personaVisible(s.agent))
    .filter(matches)
    .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));

  const renderSessionRow = (s: SessionInfo, opts: { showTime?: boolean } = {}) => (
    <SessionRow
      key={s.session_id}
      s={s}
      activeSession={props.activeSession}
      editingId={editingId}
      editValue={editValue}
      confirmDelId={confirmDelId}
      rowMenu={rowMenu}
      onSelectSession={props.onSelectSession}
      onRenameSession={props.onRenameSession}
      onTogglePin={props.onTogglePin}
      onArchiveSession={props.onArchiveSession}
      onDeleteSession={props.onDeleteSession}
      setEditingId={setEditingId}
      setEditValue={setEditValue}
      setConfirmDelId={setConfirmDelId}
      openRowMenu={openRowMenu}
      closeRowMenu={closeRowMenu}
      opts={opts}
    />
  );

  const pinnedBand = () =>
    pinnedSessions.length > 0 ? (
      <div>
        <div className="px-1.5 text-[10.5px] uppercase tracking-[0.07em] text-faint font-semibold mb-1">
          Pinned
        </div>
        <div className="space-y-0.5">
          {pinnedSessions.map((s) => renderSessionRow(s))}
        </div>
      </div>
    ) : null;

  const agentsWithSessions = new Set(
    props.sessions
      .filter((s) => !s.archived && !s.session_id.startsWith("__"))
      .map((s) => s.agent),
  );

  const visibleSurfaces = (
    personas
      ? personas
          .filter((p) => (p.enabled && p.surfaced) || agentsWithSessions.has(p.id))
          .sort((a, b) => Number(b.default) - Number(a.default))
          .map(surfaceFromPersona)
      : SURFACES.filter(
          (s) => s.key === "cowork" || props.surfaces[s.key as keyof SurfaceVisibility],
        )
  ).filter((s) => personaVisible(s.key));

  const isCurrent = (key: string) => props.agent === key;
  const isExpanded = (key: string) => openKey === key;
  const onHeaderClick = (key: string) => setOpenKey((k) => (k === key ? null : key));

  const byProject = useMemo(() => {
    const grouped = new Map<string, SessionInfo[]>();
    for (const s of mine) {
      if (!grouped.has(s.workspace)) grouped.set(s.workspace, []);
      grouped.get(s.workspace)!.push(s);
    }
    return grouped;
  }, [mine]);

  const filteredByProject = useMemo(() => {
    const grouped = new Map<string, SessionInfo[]>();
    for (const [proj, list] of byProject) grouped.set(proj, list.filter(matches));
    return grouped;
  }, [byProject]);

  const projectOrder: string[] = [];
  const seen = new Set<string>();
  if (props.workspace && browseKey === props.agent) {
    projectOrder.push(props.workspace);
    seen.add(props.workspace);
  }
  for (const s of mine) {
    if (s.workspace && !seen.has(s.workspace)) {
      seen.add(s.workspace);
      projectOrder.push(s.workspace);
    }
  }

  const surfaceBody = () => (
    <div className="space-y-1 px-1.5 pb-2 pt-0.5">
      {workspaceSurface ? (
        <>
          <div className="flex items-center justify-between px-1.5 pt-1">
            <span className="text-[10.5px] uppercase tracking-[0.07em] text-faint font-semibold">
              Projects
            </span>
            <button
              className="w-5 h-5 grid place-items-center rounded text-faint hover:text-fg hover:bg-panel"
              title="New project"
              aria-label="New project"
              onClick={() => props.onNewProject(browseKey)}
            >
              <Icon name="folderPlus" size={14} />
            </button>
          </div>
          <div className="space-y-0.5">
            {projectOrder.length === 0 && (
              <div className="px-2 py-1.5 text-[12px] text-faint leading-snug">
                No projects yet — start one with the + above.
              </div>
            )}
            {projectOrder.map((proj) => {
              const list = filteredByProject.get(proj) || [];
              const isActive = proj === props.workspace;
              const activeInOrder = !!props.workspace && projectOrder.includes(props.workspace);
              const defaultOpen = isActive || (!activeInOrder && proj === projectOrder[0]);
              const open = defaultOpen !== projToggled.has(proj);
              const showAll = projShowAll.has(proj);
              const shown = showAll ? list : list.slice(0, peek);
              return (
                <div key={proj}>
                  <div
                    className={
                      "flex items-center gap-1.5 px-1.5 py-1 rounded-md cursor-pointer select-none hover:bg-panel " +
                      (isActive ? "text-fg" : "text-muted hover:text-fg")
                    }
                    onClick={() => setProjToggled((s) => toggleSet(s, proj))}
                    title={proj}
                  >
                    <Icon name="folder" size={15} className="shrink-0" />
                    <span
                      className={
                        "truncate min-w-0 text-[12.5px] " + (isActive ? "font-semibold" : "font-medium")
                      }
                    >
                      {baseName(proj)}
                    </span>
                    <Icon
                      name={open ? "chevronDown" : "chevronRight"}
                      size={12}
                      className="text-faint shrink-0"
                    />
                  </div>
                  {open &&
                    (list.length > 0 ? (
                      <div className="space-y-0.5 pl-[19px]">
                        {shown.map((s) => renderSessionRow(s, { showTime: true }))}
                        {!showAll && list.length > peek && (
                          <button
                            className="px-2 py-1 text-[12px] text-faint hover:text-muted"
                            onClick={() => setProjShowAll((s) => toggleSet(s, proj))}
                          >
                            Show more ({list.length - peek})
                          </button>
                        )}
                      </div>
                    ) : (
                      <div className="px-2 py-1.5 pl-[19px] text-[12px] text-faint leading-snug">
                        No conversations in this project yet.
                      </div>
                    ))}
                </div>
              );
            })}
          </div>
        </>
      ) : (
        <div className="space-y-0.5">
          {mine.filter(matches).length === 0 ? (
            <div className="px-2 py-1.5 text-[12px] text-faint leading-snug">
              No conversations yet.
            </div>
          ) : (
            <>
              {(personaShowAll.has(browseKey)
                ? mine.filter(matches)
                : mine.filter(matches).slice(0, peek)
              ).map((s) => renderSessionRow(s))}
              {!personaShowAll.has(browseKey) && mine.filter(matches).length > peek && (
                <button
                  className="px-2 py-1 text-[12px] text-faint hover:text-muted"
                  onClick={() => setPersonaShowAll((s) => toggleSet(s, browseKey))}
                >
                  Show more ({mine.filter(matches).length - peek})
                </button>
              )}
            </>
          )}
        </div>
      )}

      {archived.length > 0 && (
        <div className="mt-2 pt-1.5 border-t border-border">
          <button
            className="w-full flex items-center gap-1.5 px-1.5 py-1 rounded text-[12px] text-faint hover:text-muted"
            onClick={() => setShowArchived((v) => !v)}
          >
            <Icon name={showArchived ? "chevronDown" : "chevronRight"} size={13} className="shrink-0" />
            Archived ({archived.length})
          </button>
          {showArchived && (
            <div className="space-y-0.5 mt-0.5">{archived.filter(matches).map((s) => renderSessionRow(s))}</div>
          )}
        </div>
      )}
    </div>
  );

  return (
    <div
      className="sidebar flex flex-col min-h-0 bg-panel border-r border-border"
      onMouseLeave={props.onPeekLeave}
    >
      <div className="brand px-3.5 pt-2.5 pb-2 flex items-center gap-2" data-tauri-drag-region>
        {props.onCollapse && (
          <button
            className="nav-pin-btn w-7 h-7 grid place-items-center rounded-md text-faint hover:text-fg hover:bg-bg shrink-0"
            title={props.collapsed ? "Dock sidebar (⌘B)" : "Collapse sidebar (⌘B)"}
            aria-label={props.collapsed ? "Dock sidebar" : "Collapse sidebar"}
            onClick={props.onCollapse}
          >
            <Icon name="sidebar" size={16} />
          </button>
        )}
        <div className="brand-wordmark text-[15px]">OpenWorker<span className="beta-tag">BETA</span></div>
      </div>

      <NewSessionSplit
        personas={personas}
        current={props.agent}
        onNew={props.onNewSession}
        onManage={props.onManagePersonas}
      />

      <div className="px-2.5 mt-1">
        <button
          className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-[13px] text-left text-muted hover:bg-bg hover:text-fg"
          onClick={() => setSearchModalOpen(true)}
        >
          <Icon name="search" size={15} className="shrink-0" /> Search
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2.5 mt-3 pb-2">
        <div className="space-y-4">
          {pinnedBand()}
          <div>
            <div className="relative flex items-center justify-between px-1.5 mb-1" data-testid="recent-header">
              <span className="text-[10.5px] uppercase tracking-[0.07em] text-faint font-semibold">
                Recent
              </span>
              <button
                className="w-6 h-6 grid place-items-center rounded-md text-faint hover:text-fg hover:bg-bg -mr-1"
                title="Group & filter conversations"
                aria-label="Group and filter conversations"
                onClick={() => setGroupMenuOpen((v) => !v)}
              >
                <Icon name="sliders" size={14} />
              </button>
              {groupMenuOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setGroupMenuOpen(false)} />
                  <div
                    className="absolute right-0 top-7 z-50 w-56 rounded-md border border-border bg-panel shadow-xl p-1.5"
                    role="menu"
                    data-testid="group-filter-menu"
                  >
                    <div className="px-2 pt-1 pb-1 text-[10.5px] uppercase tracking-[0.06em] text-faint font-semibold">
                      Group by
                    </div>
                    {([["grouped", "Persona"], ["flat", "Chronological"]] as ["flat" | "grouped", string][]).map(
                      ([key, label]) => (
                        <button
                          key={key}
                          className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-[13px] text-left hover:bg-bg"
                          onClick={() => setGroupBy(key)}
                        >
                          <span className="flex-1">{label}</span>
                          {layout === key && <span className="text-accent text-[12px]">✓</span>}
                        </button>
                      ),
                    )}
                  </div>
                </>
              )}
            </div>
            {layout === "grouped" ? (
              <div className="space-y-1.5">
                {visibleSurfaces.map((s) => {
                  const expanded = isExpanded(s.key);
                  return (
                    <div
                      key={s.key}
                      className={expanded ? "rounded-md bg-bg/70 overflow-hidden" : ""}
                    >
                      <div
                        className={
                          "flex items-center gap-2.5 px-2 py-2 cursor-pointer select-none " +
                          (expanded
                            ? ""
                            : isCurrent(s.key)
                              ? "rounded-md bg-bg"
                              : "rounded-md hover:bg-bg")
                        }
                        onClick={() => onHeaderClick(s.key)}
                      >
                        <span
                          className={
                            "min-w-0 flex-1 truncate text-[13px] " +
                            (isCurrent(s.key) ? "font-semibold text-fg" : "font-medium text-fg")
                          }
                        >
                          {s.label}
                        </span>
                        <LiveDot state={liveByPersona.get(s.key)} />
                        <AttnBadge n={attnByPersona.get(s.key) || 0} />
                        <Icon
                          name={expanded ? "chevronDown" : "chevronRight"}
                          size={15}
                          className="text-faint shrink-0"
                        />
                      </div>
                      {expanded && surfaceBody()}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="space-y-0.5">
                {recentSessions.length === 0 ? (
                  <div className="px-2 py-1.5 text-[12px] text-faint leading-snug">
                    No conversations yet.
                  </div>
                ) : (
                  <>
                    {(recentExpanded
                      ? recentSessions
                      : recentSessions.slice(0, RECENT_PEEK)
                    ).map((s) => renderSessionRow(s))}
                    {recentSessions.length > RECENT_PEEK && (
                      <button
                        className="w-full text-left px-2 py-1.5 text-[12px] text-muted hover:text-fg"
                        onClick={() => setRecentExpanded((v) => !v)}
                      >
                        {recentExpanded
                          ? "Show less"
                          : `Show ${recentSessions.length - RECENT_PEEK} more`}
                      </button>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="px-2.5 py-2 border-t border-border">
        <div className="relative">
          {appMenuOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setAppMenuOpen(false)} />
              <div
                className="absolute z-40 bottom-full left-0 right-0 mb-1 rounded-md border border-border bg-panel shadow-2xl py-1"
                data-testid="account-menu"
                role="menu"
              >
                {appMenuItem(
                  "inbox",
                  "Inbox",
                  props.onOpenInbox,
                  props.inboxActive,
                  <AttnBadge n={totalAttention} />,
                )}
                {appMenuItem("plug", "Connectors", props.onOpenIntegrations, props.integrationsActive)}
                <div className="h-px bg-line my-1 mx-2" />
                {appMenuItem(
                  "gear",
                  "Settings",
                  props.onManage,
                  false,
                  <span className="text-[11px] text-faint">⌘ ,</span>,
                )}
                {appMenuItem("audit", "Activity", props.onOpenAudit, props.auditActive)}
                <div className="h-px bg-line my-1 mx-2" />
                {authState.status === "authenticated" && (
                  <div className="px-3 py-1.5 text-[11px] text-faint truncate" data-testid="account-email">
                    {authState.user.email}
                  </div>
                )}
                {appMenuItem("signOut", "Sign out", async () => {
                  setAppMenuOpen(false);
                  await signOut();
                  navigate("/signin", { replace: true });
                })}
              </div>
            </>
          )}

          <button
            className={
              "w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-[13px] text-left " +
              (appMenuOpen ? "bg-bg text-fg" : "hover:bg-bg")
            }
            data-testid="account-row"
            onClick={() => setAppMenuOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={appMenuOpen}
            aria-label="App Menu"
          >
            <Icon name="gear" size={15} className="text-muted shrink-0" />
            <span className="truncate flex-1">
              {authState.status === "authenticated"
                ? authState.user.full_name
                : "Settings & Activity"}
            </span>
            {inboxUnlocked && (
              <span
                className={
                  "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11.5px] shrink-0 cursor-pointer " +
                  (totalAttention > 0
                    ? "bg-accent/20 text-accent font-semibold"
                    : "text-faint hover:text-fg")
                }
                data-testid="inbox-chip"
                role="button"
                aria-label={
                  totalAttention > 0 ? `Inbox — ${totalAttention} items need you` : "Inbox"
                }
                title={totalAttention > 0 ? `Inbox — ${totalAttention} items need you` : "Inbox"}
                onClick={(e) => {
                  e.stopPropagation();
                  setAppMenuOpen(false);
                  props.onOpenInbox();
                }}
              >
                <Icon name="inbox" size={13} />
                {totalAttention > 0 ? totalAttention : null}
              </span>
            )}
            <Icon
              name="chevronDown"
              size={14}
              className={"text-faint shrink-0 transition-transform " + (appMenuOpen ? "" : "rotate-180")}
            />
          </button>
        </div>
      </div>

      {searchModalOpen && (
        <SearchModal
          sessions={props.sessions}
          personas={personas ?? undefined}
          onSelect={(id, ws, ag) => {
            setSearchModalOpen(false);
            props.onSelectSession(id, ws, ag);
          }}
          onClose={() => setSearchModalOpen(false)}
        />
      )}
    </div>
  );
}
