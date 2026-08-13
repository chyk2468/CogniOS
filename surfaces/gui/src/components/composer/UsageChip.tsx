import { useState } from "react";
import type { SessionUsage } from "../../types";
import { formatTokens, totalTokens } from "../../usage";

const shortModel = (m: string) => (m.includes(":") ? m.split(":").slice(1).join(":") : m);

export function UsageChip({
  usage,
  contextWindow,
  contextBar,
  model: _model,
  modelLabels,
}: {
  usage: SessionUsage;
  contextWindow?: number;
  contextBar?: boolean;
  model: string;
  modelLabels?: Record<string, string>;
}) {
  const [open, setOpen] = useState(false);
  const total = totalTokens(usage);
  const pct = contextWindow
    ? Math.min(100, Math.round((usage.context / contextWindow) * 100))
    : null;
  const showBar = pct !== null && contextBar === true;

  const labelFor = (id: string) =>
    id === "unknown" ? "Unknown model" : modelLabels?.[id] || shortModel(id);

  const stat = (label: string, value: number) => (
    <div className="flex items-baseline justify-between text-[11.5px] leading-snug">
      <span className="text-faint">{label}</span>
      <span className="text-fg tabular-nums">{formatTokens(value)}</span>
    </div>
  );

  return (
    <div className="relative">
      <button
        className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11.5px] text-muted hover:text-fg hover:bg-bg shrink-0"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Token usage"
        title={
          showBar
            ? `Context window ${pct}% full · ${formatTokens(total)} tokens this session`
            : `Token usage this session: ${formatTokens(total)}`
        }
        data-testid="usage-chip"
      >
        {showBar ? (
          <span className="w-12 h-1.5 rounded-md bg-line overflow-hidden" aria-hidden="true">
            <span
              className="block h-full bg-accent transition-all"
              style={{ width: `${Math.max(pct as number, 4)}%` }}
            />
          </span>
        ) : (
          <span className="tabular-nums">{formatTokens(total)}</span>
        )}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute z-40 bottom-full mb-1 right-0 w-[280px] rounded-md border border-border bg-panel shadow-2xl p-3"
            role="menu"
            data-testid="usage-popover"
          >
            {contextWindow ? (
              <div className="mb-2.5">
                <div className="text-[10.5px] uppercase tracking-[0.06em] text-faint font-semibold mb-1">
                  Context window
                </div>
                <div className="h-1.5 rounded-md bg-line overflow-hidden">
                  <div
                    className="h-full bg-accent transition-all"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <div className="mt-1 text-[11.5px] text-muted tabular-nums">
                  {formatTokens(usage.context)} of {formatTokens(contextWindow)} · {pct}%
                </div>
              </div>
            ) : usage.context > 0 ? (
              <div className="mb-2.5 text-[11.5px] text-muted tabular-nums">
                In context now: {formatTokens(usage.context)} tokens
              </div>
            ) : null}
            <div className="text-[10.5px] uppercase tracking-[0.06em] text-faint font-semibold mb-1">
              Session totals
            </div>
            <div className="flex flex-col gap-1.5">
              {Object.entries(usage.byModel).map(([id, t]) => (
                <div key={id}>
                  <div className="text-[12px] text-fg font-medium truncate" title={id}>
                    {labelFor(id)}
                  </div>
                  <div className="mt-0.5 flex flex-col gap-0.5">
                    {t.cache_read + t.cache_write > 0 ? (
                      <>
                        {stat("Uncached input", t.input)}
                        {stat("Cache reads", t.cache_read)}
                        {stat("Cache writes", t.cache_write)}
                        {stat("Total input", t.input + t.cache_read + t.cache_write)}
                      </>
                    ) : (
                      stat("Input", t.input)
                    )}
                    {stat("Output", t.output)}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-2 pt-2 border-t border-border flex items-baseline justify-between text-[11.5px]">
              <span className="text-faint">Total</span>
              <span className="text-fg tabular-nums">{formatTokens(total)} tokens</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
