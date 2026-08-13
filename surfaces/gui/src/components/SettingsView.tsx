import { useState } from "react";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { ModelsTab } from "./ManageTabs";
import { MemorySection } from "./MemorySection";
import { PersonasTab } from "./PersonasTab";
import { SkillsTab } from "./SkillsTab";
import { showPersonas } from "../flags";
import { AppearanceSection } from "./settings/GeneralTab";
import { VoiceInputSection } from "./settings/VoiceInputSection";

type SetTab = "appearance" | "models" | "skills" | "voice" | "memory" | "personas";



const SET_TABS: {
  key: SetTab;
  label: string;
  icon: "sliders" | "code" | "mic" | "archive" | "sparkle" | "book";
}[] = [
  { key: "appearance", label: "General", icon: "sliders" },
  { key: "models", label: "Models", icon: "code" },
  { key: "skills", label: "Skills", icon: "book" },
  { key: "voice", label: "Voice input", icon: "mic" },
  { key: "memory", label: "Memory", icon: "archive" },
  { key: "personas", label: "Personas", icon: "sparkle" },
];

import { FloatingWindow } from "./layout/FloatingWindow";
export function SettingsView({
  initialTab,
  onOpenPersona,
  onCreateSkill,
  onClose,
}: {
  initialTab?: SetTab;
  onOpenPersona?: (id: string) => void;
  onCreateSkill?: (description: string) => void;
  onClose?: () => void;
}) {
  const personas = showPersonas();
  const tabs = personas ? SET_TABS : SET_TABS.filter((t) => t.key !== "personas");
  const wanted = initialTab && (personas || initialTab !== "personas") ? initialTab : "appearance";
  const [tab, setTab] = useState<SetTab>(wanted);

  return (
    <FloatingWindow
      id="settings"
      title="Settings"
      icon="gear"
      onClose={onClose || (() => {})}
    >
      <div className="flex-1 min-w-0 flex bg-bg h-full overflow-hidden">
        <nav className="page-subnav w-[195px] shrink-0 border-r border-border bg-panel/50 px-2.5 py-3 flex flex-col justify-between overflow-y-auto">
          <div className="space-y-0.5">
            {tabs.map((t) => {
              const active = tab === t.key;
              return (
                <button
                  key={t.key}
                  className={
                    "w-full text-left px-2.5 py-2 rounded-md text-[13px] flex items-center gap-2 transition-colors " +
                    (active ? "bg-accent/15 text-accent font-semibold border-l-2 border-accent" : "text-muted hover:bg-bg hover:text-fg")
                  }
                  onClick={() => setTab(t.key)}
                >
                  <Icon name={t.icon} size={15} /> {t.label}
                </button>
              );
            })}
          </div>
        </nav>

        <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll p-6">
          {tab === "appearance" ? (
            <AppearanceSection />
          ) : tab === "models" ? (
            <section>
              <PanelHead
                title="Models"
                sub="Providers and the models offered in the composer's picker. Keys are stored only on this computer."
              />
              <ModelsTab />
            </section>
          ) : tab === "skills" ? (
            <SkillsTab onCreateSkill={onCreateSkill} />
          ) : tab === "voice" ? (
            <VoiceInputSection />
          ) : tab === "memory" ? (
            <MemorySection />
          ) : (
            <PersonasSection onOpenPersona={onOpenPersona} />
          )}
        </div>
      </div>
    </FloatingWindow>
  );
}

function PersonasSection({ onOpenPersona }: { onOpenPersona?: (id: string) => void }) {
  return (
    <section>
      <PanelHead
        title="Personas"
        sub="Which coworkers are enabled and shown in the picker, plus installing new persona bundles."
      />
      <PersonasTab onOpenPersona={onOpenPersona} />
    </section>
  );
}
