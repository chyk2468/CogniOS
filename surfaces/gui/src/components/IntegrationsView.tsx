import { useEffect, useState } from "react";
import { getConnectors } from "../api";
import { McpTab } from "./ManageTabs";
import { ConnectorsSection } from "./connectors/ConnectorsSection";
import { Icon } from "./Icon";

// The Connectors surface (renamed from "Integrations", §26) keeps the left sub-nav, now just
// Connectors · MCP. The old "Messaging routing" tab (and its ⚠ unrouted badge) moved whole to
// Inbox ▸ Configure (§28): inbox-delivery config belongs with the Inbox, and Unrouted is
// "messages that never reached you". The one remaining Activity is the audit log, reached from
// the account menu.
type IntTab = "connectors" | "mcp";

// Fixed sub-nav (UX-DECISIONS §21): connector detail lives as a SUBPAGE under
// Connectors, never as a nav item — the nav must not grow per connector.
const INT_TABS: { key: IntTab; label: string; icon: "plug" | "code" }[] = [
  { key: "connectors", label: "Connectors", icon: "plug" },
  { key: "mcp", label: "MCP servers", icon: "code" },
];

import { FloatingWindow } from "./layout/FloatingWindow";

export function IntegrationsView({ onClose }: { onClose?: () => void }) {
  const [tab, setTab] = useState<IntTab>("connectors");
  const [connCount, setConnCount] = useState<number | null>(null);

  useEffect(() => {
    const load = () => {
      getConnectors().then((cs) => setConnCount(cs.length)).catch(() => {});
    };
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <FloatingWindow
      id="integrations"
      title="Connectors & MCP"
      icon="plug"
      onClose={onClose || (() => {})}
    >
      <div className="flex-1 min-w-0 flex bg-bg h-full overflow-hidden">
        <nav className="page-subnav w-[195px] shrink-0 border-r border-border bg-panel/50 px-2.5 py-3 flex flex-col justify-between overflow-y-auto">
          <div className="space-y-0.5">
            {INT_TABS.map((t) => {
              const active = tab === t.key;
              return (
                <button
                  key={t.key}
                  className={
                    "w-full text-left px-2.5 py-2 rounded-md text-[13px] flex items-center justify-between transition-colors " +
                    (active
                      ? "bg-accent/15 text-accent font-semibold border-l-2 border-accent"
                      : "text-muted hover:bg-bg hover:text-fg")
                  }
                  onClick={() => setTab(t.key)}
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <Icon name={t.icon} size={15} /> {t.label}
                  </span>
                  {t.key === "connectors" && connCount != null && (
                    <span className={"text-[11px] shrink-0 " + (active ? "text-accent font-bold" : "text-faint")}>
                      {connCount}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </nav>

        <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll p-6">
          {tab === "connectors" ? (
            <section>
              <PanelHead
                title="Connectors"
                sub="Apps and tools your coworkers can use. Connected ones come first."
              />
              <ConnectorsSection />
            </section>
          ) : (
            <section>
              <PanelHead
                title="MCP servers"
                sub="External tool servers (stdio or HTTP), shared across all agents."
              />
              <McpTab />
            </section>
          )}
        </div>
      </div>
    </FloatingWindow>
  );
}

export function PanelHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-[18px] font-semibold tracking-tight">{title}</h2>
      <p className="text-[12.5px] text-muted mt-0.5">{sub}</p>
    </div>
  );
}
