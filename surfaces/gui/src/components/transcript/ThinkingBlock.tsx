import { useState } from "react";
import { Icon } from "../Icon";

export function ThinkingBlock({ text, live }: { text: string; live?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="thinking my-2 rounded-md border border-border bg-panel/50 p-2 text-[12.5px]">
      <button
        className="thinking-head flex items-center gap-1.5 text-muted hover:text-fg font-medium cursor-pointer"
        onClick={() => setOpen((v) => !v)}
        data-testid="thinking-toggle"
      >
        <Icon name="chevronDown" size={12} className={"thinking-caret transition-transform" + (open ? " rotate-180" : "")} />
        <span className={live ? "thinking-live text-accent animate-pulse font-mono" : undefined}>
          {live ? "Thinking…" : "Thought process"}
        </span>
      </button>
      {open && (
        <div className="thinking-body mt-2 pt-2 border-t border-border/50 text-faint font-mono text-[12px] whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto" data-testid="thinking-body">
          {text}
        </div>
      )}
    </div>
  );
}
