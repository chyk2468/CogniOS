import { useState } from "react";
import { Icon } from "../Icon";
import { Toggle } from "../Toggle";
import type { Option } from "../Dropdown";

const PERMISSION_OPTIONS: Option[] = [
  { value: "discuss", label: "Discuss", description: "Chat and explore — no edits or commands" },
  { value: "interactive", label: "Ask for approval", description: "Ask before edits and commands" },
  { value: "auto", label: "Full access", description: "Run everything without asking" },
];

export function ModeMenu({
  mode,
  onModeChange,
  unattended,
  onUnattendedChange,
}: {
  mode: string;
  onModeChange: (mode: string) => void;
  unattended?: boolean;
  onUnattendedChange?: (on: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = PERMISSION_OPTIONS.find((o) => o.value === mode);
  return (
    <div className="relative">
      <button
        className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[12px] text-muted hover:text-fg hover:bg-bg shrink-0"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Mode"
        title={
          `Mode: ${current?.label || mode}` +
          (unattended ? " · approvals go to the Inbox" : "")
        }
      >
        {current?.label || mode}
        <Icon name="chevronDown" size={11} className="text-faint" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute z-40 bottom-full mb-1 left-0 w-[260px] rounded-md border border-border bg-panel shadow-2xl p-1.5"
            role="menu"
            data-testid="mode-menu"
          >
            {PERMISSION_OPTIONS.map((o) => (
              <button
                key={o.value}
                className="w-full flex flex-col items-start px-2.5 py-1.5 rounded-md text-left hover:bg-bg"
                onClick={() => {
                  onModeChange(o.value);
                  setOpen(false);
                }}
              >
                <span
                  className={
                    "text-[13px] " + (o.value === mode ? "font-medium text-accent" : "text-fg")
                  }
                >
                  {o.label}
                  {o.value === mode && <span className="ml-1.5">✓</span>}
                </span>
                <span className="text-[11px] text-faint leading-snug">{o.description}</span>
              </button>
            ))}
            {onUnattendedChange && (
              <>
                <div className="my-1 border-t border-border" />
                <div className="flex items-center gap-2 px-2.5 py-1.5">
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13px] text-fg">Send approvals to Inbox</span>
                    <span className="block text-[11px] text-faint leading-snug">
                      Approvals &amp; questions go to the Inbox; the agent keeps working.
                    </span>
                  </span>
                  <Toggle
                    checked={!!unattended}
                    onChange={onUnattendedChange}
                    title="Send approvals to the Inbox"
                  />
                </div>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
