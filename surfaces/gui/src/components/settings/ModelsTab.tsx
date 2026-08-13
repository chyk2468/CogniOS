import { useEffect, useState } from "react";
import {
  getSettings,
  setDefaultModel,
  type ModelSettings,
} from "../../api";
import { ModelChecklist } from "../ModelChecklist";
import { ProviderCards, ProviderForm, useProviderSetup } from "../../providers/ProviderSetup";
import { Icon } from "../Icon";

const SEC_H = "text-[11px] uppercase tracking-[0.05em] text-faint font-semibold";
const CARD = "rounded-md border border-border bg-panel p-4 mb-4 shadow-sm";
const LABEL = "w-32 text-[13px] font-medium text-fg shrink-0";
const SELECT = "flex-1 px-3 py-1.5 rounded-md border border-border bg-bg text-[13px] text-fg outline-none focus:border-accent font-mono";

export function ModelsTab() {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const refreshSettings = () => getSettings().then(setSettings).catch(() => setSettings(null));
  const ps = useProviderSetup({ onSaved: refreshSettings });

  const [utilityModel, setUtilityModel] = useState<string>("");
  const [visionEnabled, setVisionEnabled] = useState<boolean>(true);
  const [visionModel, setVisionModel] = useState<string>("");

  useEffect(() => {
    refreshSettings();
  }, []);

  if (!settings) return <div className="text-[13px] text-muted">Loading models…</div>;

  const info = ps.info;
  const knownNames = ps.providers.map((p) => p.name);
  const availableModels = settings.models || [];
  const modelLabels = settings.model_labels || {};

  const handleDefaultModelChange = async (m: string) => {
    await setDefaultModel(m);
    refreshSettings();
  };

  // If configuring a specific provider (e.g. OpenAI, Anthropic)
  if (ps.sel !== null) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => ps.backToGallery()}
          className="flex items-center gap-1.5 text-[12.5px] text-accent hover:underline mb-2 font-medium"
        >
          ← Back to model settings
        </button>

        <ProviderForm
          ps={ps}
          tp="set"
          footer={
            ps.credentialed ? (
              <button
                className="text-[12.5px] text-danger hover:underline underline-offset-2"
                data-testid="set-remove-key"
                onClick={() => {
                  if (window.confirm(`Remove the ${info?.title} key from this computer?`)) ps.removeKey();
                }}
              >
                Remove key…
              </button>
            ) : null
          }
        />

        {info?.configured && (
          <div className="mt-4">
            <div className={SEC_H + " mb-1.5"}>Available Models</div>
            <p className="text-[12px] text-muted mb-2.5 leading-relaxed">
              Ticked models show up in the composer's model picker.
            </p>
            <ModelChecklist
              provider={ps.sel}
              knownProviders={knownNames}
              suggested={info?.suggested_models || []}
              curated={settings.models}
              defaultModel={settings.model}
              labels={settings.model_labels}
              onChanged={(next) => setSettings((s) => (s ? { ...s, models: next.models, model: next.model } : s))}
            />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 1. Default Chat Model Card */}
      <div className={CARD}>
        <h2 className="text-[14px] font-semibold text-fg flex items-center gap-2 mb-1">
          <Icon name="chat" size={15} className="text-accent" />
          Default Chat Model
        </h2>
        <div className="text-[12px] text-muted mb-3 leading-relaxed">
          The primary AI model used when creating a new chat session.
        </div>
        <div className="flex items-center gap-3">
          <label className={LABEL}>Primary Model</label>
          <select
            className={SELECT}
            value={settings.model}
            onChange={(e) => handleDefaultModelChange(e.target.value)}
          >
            {availableModels.map((m) => (
              <option key={m} value={m}>
                {modelLabels[m] || m}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 2. Utility Model Card */}
      <div className={CARD}>
        <h2 className="text-[14px] font-semibold text-fg flex items-center gap-2 mb-1">
          <Icon name="sliders" size={15} className="text-accent" />
          Utility Model
          <span className="text-[11px] font-normal text-muted ml-1">(Local / Fast)</span>
        </h2>
        <div className="text-[12px] text-muted mb-3 leading-relaxed">
          Runs background tasks (context compaction, auto-titling, memory retrieval) on a fast/local model.
        </div>
        <div className="flex items-center gap-3">
          <label className={LABEL}>Utility Model</label>
          <select
            className={SELECT}
            value={utilityModel}
            onChange={(e) => setUtilityModel(e.target.value)}
          >
            <option value="">Same as primary chat model (default)</option>
            {availableModels.map((m) => (
              <option key={m} value={m}>
                {modelLabels[m] || m}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 3. Vision Model Card */}
      <div className={CARD}>
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-[14px] font-semibold text-fg flex items-center gap-2">
            <Icon name="sparkle" size={15} className="text-accent" />
            Vision Model
          </h2>
          <label className="flex items-center gap-2 text-[12px] text-muted cursor-pointer select-none">
            <input
              type="checkbox"
              className="accent-accent"
              checked={visionEnabled}
              onChange={(e) => setVisionEnabled(e.target.checked)}
            />
            Enabled
          </label>
        </div>
        <div className="text-[12px] text-muted mb-3 leading-relaxed">
          Analyze image attachments with a vision-capable model.
        </div>
        {visionEnabled && (
          <div className="flex items-center gap-3">
            <label className={LABEL}>Vision Model</label>
            <select
              className={SELECT}
              value={visionModel}
              onChange={(e) => setVisionModel(e.target.value)}
            >
              <option value="">Auto-detect from primary model</option>
              {availableModels.map((m) => (
                <option key={m} value={m}>
                  {modelLabels[m] || m}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* 4. Provider Keys & Connection Grid */}
      <div className={CARD}>
        <div className={SEC_H + " mb-2.5"}>Providers &amp; API Keys</div>
        <div className="text-[12px] text-muted mb-3 leading-relaxed">
          Click any provider to set up API keys or manage active models.
        </div>
        <ProviderCards ps={ps} tp="set" gridClass="grid grid-cols-2 xl:grid-cols-3 gap-2.5" lastUsed />
      </div>
    </div>
  );
}
