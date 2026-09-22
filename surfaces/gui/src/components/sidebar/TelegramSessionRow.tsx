import type { SessionInfo } from "../../types";
import { Icon, type IconName } from "../Icon";
import { compactAge } from "./SidebarBadges";

interface TelegramSessionRowProps {
  s: SessionInfo;
  activeSession: string;
  editingId: string | null;
  editValue: string;
  confirmDelId: string | null;
  rowMenu: { id: string; top: number; left: number; anchor: HTMLElement } | null;
  onSelectSession: (id: string, workspace: string, agent: string) => void;
  onRenameSession: (id: string, title: string) => void;
  onTogglePin: (id: string, pinned: boolean) => void;
  onArchiveSession: (id: string, archived: boolean) => void;
  onDeleteSession: (id: string) => void;
  setEditingId: (id: string | null) => void;
  setEditValue: (val: string) => void;
  setConfirmDelId: (id: string | null) => void;
  openRowMenu: (id: string, anchor: HTMLElement) => void;
  closeRowMenu: () => void;
}

export function TelegramSessionRow({
  s,
  activeSession,
  editingId,
  editValue,
  confirmDelId,
  rowMenu,
  onSelectSession,
  onRenameSession,
  onTogglePin,
  onArchiveSession,
  onDeleteSession,
  setEditingId,
  setEditValue,
  setConfirmDelId,
  openRowMenu,
  closeRowMenu,
}: TelegramSessionRowProps) {
  const chatName = s.telegram_username || s.title || (s.telegram_chat_id ? `Chat ${s.telegram_chat_id}` : s.session_id);
  const lastMsg = s.last_message || (s.messages ? `${s.messages} messages` : "No messages yet");
  const editing = editingId === s.session_id;
  const active = s.session_id === activeSession;
  const menuOpen = rowMenu?.id === s.session_id;
  const unread = s.unread_count || 0;
  const age = compactAge(s.updated_at);

  const commitRename = () => {
    const next = editValue.trim();
    if (next && next !== chatName) onRenameSession(s.session_id, next);
    setEditingId(null);
  };

  const item = (testid: string, icon: IconName, label: string, onClick: () => void) => (
    <button
      className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12.5px] text-left hover:bg-bg"
      data-testid={testid}
      role="menuitem"
      onClick={() => {
        closeRowMenu();
        onClick();
      }}
    >
      <Icon name={icon} size={13} className="shrink-0 text-muted" />
      <span className="flex-1">{label}</span>
    </button>
  );

  const rowActions = () => (
    <span
      className={(menuOpen ? "flex" : "hidden group-hover:flex") + " items-center shrink-0 ml-1"}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        title="Session actions"
        aria-label="Session actions"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        data-testid="tg-row-menu"
        className={
          "w-5 h-5 grid place-items-center rounded-md hover:bg-bg " +
          (menuOpen ? "text-fg bg-bg" : "text-faint hover:text-fg")
        }
        onClick={(e) => (menuOpen ? closeRowMenu() : openRowMenu(s.session_id, e.currentTarget))}
      >
        <Icon name="moreHorizontal" size={14} className="rotate-90" />
      </button>
      {menuOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={closeRowMenu} />
          <div
            className="fixed z-50 w-40 rounded-md border border-border bg-panel shadow-xl py-1"
            style={{ top: rowMenu!.top, left: rowMenu!.left }}
            role="menu"
          >
            {item("tg-row-menu-rename", "pencil", "Rename", () => {
              setEditingId(s.session_id);
              setEditValue(chatName);
            })}
            {item("tg-row-menu-pin", "pin", s.pinned ? "Unpin" : "Pin", () =>
              onTogglePin(s.session_id, !s.pinned),
            )}
            {item("tg-row-menu-archive", "archive", s.archived ? "Unarchive" : "Archive", () =>
              onArchiveSession(s.session_id, !s.archived),
            )}
            <div className="h-px bg-line my-1 mx-2" />
            {confirmDelId === s.session_id ? (
              <button
                title="Click again to permanently delete"
                className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12.5px] text-left font-medium text-danger hover:bg-bg"
                data-testid="tg-row-menu-delete"
                role="menuitem"
                onClick={() => {
                  closeRowMenu();
                  onDeleteSession(s.session_id);
                }}
              >
                <Icon name="trash" size={13} className="shrink-0" />
                <span className="flex-1">Delete?</span>
              </button>
            ) : (
              <button
                className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[12.5px] text-left text-danger hover:bg-bg"
                data-testid="tg-row-menu-delete"
                role="menuitem"
                onClick={() => setConfirmDelId(s.session_id)}
              >
                <Icon name="trash" size={13} className="shrink-0" />
                <span className="flex-1">Delete</span>
              </button>
            )}
          </div>
        </>
      )}
    </span>
  );

  return (
    <div
      key={s.session_id}
      className={
        "group nav-row flex flex-col px-2.5 py-1.5 rounded-lg text-[13px] cursor-pointer transition-all relative border border-transparent " +
        (active
          ? "bg-accent/15 text-fg font-medium border-l-[3px] border-l-accent pl-[18px]"
          : "text-muted hover:bg-bg hover:text-fg")
      }
      data-testid={`telegram-session-${s.session_id}`}
      onClick={() => {
        if (!editing) onSelectSession(s.session_id, s.workspace, s.agent);
      }}
      title={editing ? undefined : `${chatName} — ${lastMsg}`}
    >
      {editing ? (
        <input
          className="w-full px-1.5 py-0.5 rounded-md bg-panel border border-accent text-[13px] text-fg outline-none"
          value={editValue}
          autoFocus
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter") commitRename();
            else if (e.key === "Escape") setEditingId(null);
          }}
        />
      ) : (
        <>
          <div className="flex items-center justify-between gap-1.5 min-w-0">
            <div className="flex items-center gap-1.5 min-w-0 flex-1">
              <span className="shrink-0 w-2 h-2 rounded-full bg-[#2AABEE]" title="Telegram chat" />
              <span
                className={
                  "truncate min-w-0 text-[12.5px] " +
                  (active ? "font-semibold text-fg" : "font-medium text-fg")
                }
              >
                {chatName}
              </span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              {age && <span className="text-[11px] text-faint tabular-nums">{age}</span>}
              {unread > 0 && (
                <span
                  className="bg-[#2AABEE] text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full min-w-[16px] text-center leading-[14px]"
                  title={`${unread} unread messages`}
                >
                  {unread}
                </span>
              )}
              {rowActions()}
            </div>
          </div>
          <div className="text-[11.5px] text-faint truncate mt-0.5 pl-3.5 leading-snug">
            {lastMsg}
          </div>
        </>
      )}
    </div>
  );
}
