import { useState } from "react";
import type { Persona } from "../../api";
import { Icon } from "../Icon";
import { PersonaGlyph } from "../personaIcon";
import { shortPersonaName } from "../../personaScope";
import { showPersonas } from "../../flags";

export function NewSessionSplit({
  personas,
  current,
  onNew,
  onManage,
}: {
  personas: Persona[] | null;
  current: string;
  onNew: (agent: string) => void;
  onManage: () => void;
}) {
  const [open, setOpen] = useState(false);
  const enabled = (personas || []).filter((p) => p.enabled);
  const solo = personas !== null && enabled.length <= 1;

  return (
    <div className="px-3 pt-2 relative">
      <div className="flex">
        <button
          className={
            "newsplit-primary flex-1 text-left px-3 py-2 bg-accent text-white text-[13px] font-medium hover:opacity-95 flex items-center gap-2 " +
            (solo ? "rounded-md" : "rounded-l-md")
          }
          onClick={() => onNew(solo && enabled.length === 1 ? enabled[0].id : current)}
        >
          <Icon name="plus" size={15} className="shrink-0" /> New session
        </button>
        {!solo && (
          <button
            className="px-2.5 rounded-r-md bg-accent text-white border-l border-white/25 hover:opacity-95 flex items-center"
            title="Start with a specific persona"
            aria-label="Choose a persona"
            onClick={() => setOpen((v) => !v)}
          >
            <Icon name="chevronDown" size={13} />
          </button>
        )}
      </div>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="newsplit-menu absolute left-3 right-3 mt-1 z-30 bg-panel border border-border rounded-md shadow-xl p-1">
            <div className="px-2 py-1 text-[10.5px] uppercase tracking-[0.06em] text-faint font-semibold">
              Start a session as
            </div>
            {enabled.map((p) => (
              <button
                key={p.id}
                className="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md hover:bg-bg text-left"
                onClick={() => {
                  setOpen(false);
                  onNew(p.id);
                }}
              >
                <span className="w-6 h-6 rounded-md bg-bg border border-border grid place-items-center text-muted shrink-0">
                  <PersonaGlyph icon={p.icon} family={p.family} size={12} />
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium truncate">
                    {shortPersonaName(p.name, p.id)}
                  </span>
                  {p.tagline && (
                    <span className="block text-[11px] text-muted truncate">{p.tagline}</span>
                  )}
                </span>
              </button>
            ))}
            {showPersonas() && (
              <div className="border-t border-border mt-1 pt-1">
                <button
                  className="w-full px-2 py-1.5 rounded-md hover:bg-bg text-left text-[12.5px] text-muted"
                  onClick={() => {
                    setOpen(false);
                    onManage();
                  }}
                >
                  Manage personas…
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
