import { useEffect, useState } from "react";
import { PanelHead } from "../IntegrationsView";
import {
  getSettings,
  getTrustedWorkspaces,
  setContextBar,
  setOnboarded,
  setScratchBase,
  setSessionsPeek,
  setWorkspaceTrusted,
  type ModelSettings,
  type WorkspaceCommandTrust,
} from "../../api";
import {
  checkForUpdate,
  getAutostart,
  getKeepAwake,
  installUpdate,
  isTauri,
  pickFolder,
  setAutostart,
  setKeepAwake,
} from "../../tauri";
import { useThemePref } from "../../theme";

const CARD = "rounded-md border border-border bg-panel";
const FIELD_LABEL = "text-[12.5px] font-medium text-fg";
const FIELD_HELP = "text-[12px] text-muted mt-1.5 leading-relaxed";
const INPUT = "flex-1 min-w-0 px-3 py-2 rounded-md border border-border bg-bg text-[13px] text-fg outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-md bg-accent text-white shrink-0 disabled:opacity-40 font-medium";
const BTN_BORDERED = "text-[12.5px] px-3 py-2 rounded-md border border-border bg-bg hover:border-border shrink-0 text-fg";

export function AppearanceSection() {
  const [theme, setTheme] = useThemePref();
  const [autostart, setAuto] = useState(false);
  const [keepAwake, setKeep] = useState(false);
  const desktop = isTauri();

  useEffect(() => {
    if (isTauri()) {
      getAutostart().then((v) => setAuto(!!v));
      getKeepAwake().then((v) => setKeep(!!v));
    }
  }, []);

  const toggleAuto = async (v: boolean) => setAuto(!!(await setAutostart(v)));
  const toggleKeep = async (v: boolean) => setKeep(!!(await setKeepAwake(v)));
  const runSetupAgain = async () => {
    await setOnboarded(false);
    window.dispatchEvent(new CustomEvent("coworker:open-onboarding"));
  };

  return (
    <section>
      <PanelHead title="General" sub="How OpenWorker looks and behaves on this machine." />

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>Theme Preset</div>
        <div className="seg mt-2.5 flex flex-wrap gap-1 bg-bg p-1 rounded-md border border-border" role="radiogroup" aria-label="Appearance">
          {(["copper", "dark", "light", "midnight", "paper", "cyberpunk", "retrowave", "claude", "auto"] as const).map((p) => (
            <button key={p} className={"px-2.5 py-1 rounded-md text-[12px] capitalize " + (p === theme ? "bg-panel text-accent font-semibold shadow-sm border border-accent/40" : "text-muted hover:text-fg")} onClick={() => setTheme(p)}>
              {p}
            </button>
          ))}
        </div>
        <div className={FIELD_HELP}>Copper (Orange) theme. Auto follows your system appearance.</div>
      </div>

      <SidebarCard />
      <ContextBarCard />
      <FilesCard />
      <TrustedWorkspacesCard />

      {desktop && (
        <div className={CARD + " p-4 mb-4"}>
          <div className={FIELD_LABEL + " mb-2.5"}>Always-on</div>
          <label className="flex items-start gap-3 py-2 cursor-pointer">
            <input type="checkbox" className="mt-0.5 accent-accent" checked={autostart} onChange={(e) => toggleAuto(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-fg">Open at login</span>
              <span className="block text-[12px] text-muted">Launch OpenWorker automatically when you sign in.</span>
            </span>
          </label>
          <label className="flex items-start gap-3 py-2 cursor-pointer">
            <input type="checkbox" className="mt-0.5 accent-accent" checked={keepAwake} onChange={(e) => toggleKeep(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-fg">Keep this system awake</span>
              <span className="block text-[12px] text-muted">Prevent idle sleep so scheduled tasks fire on time.</span>
            </span>
          </label>
        </div>
      )}

      <div className={CARD + " p-4"}>
        <div className={FIELD_LABEL + " mb-2"}>Setup &amp; updates</div>
        <div className="flex items-center gap-2">
          <button className={BTN_BORDERED} onClick={runSetupAgain}>
            Run setup again
          </button>
          {desktop && <UpdateInline />}
        </div>
        <div className={FIELD_HELP}>Replays the first-run setup: model, tools, tips.</div>
      </div>
    </section>
  );
}

function TrustedWorkspacesCard() {
  const [workspaces, setWorkspaces] = useState<WorkspaceCommandTrust[] | null>(null);

  const refresh = () =>
    getTrustedWorkspaces()
      .then(setWorkspaces)
      .catch(() => setWorkspaces([]));

  useEffect(() => {
    refresh();
  }, []);

  const revoke = async (path: string) => {
    if (!window.confirm(`Revoke command trust for ${path}?`)) return;
    await setWorkspaceTrusted(path, false);
    refresh();
  };

  return (
    <div className={CARD + " p-4 mb-4"} data-testid="trusted-workspaces-card">
      <div className={FIELD_LABEL}>Trusted workspaces</div>
      <div className={FIELD_HELP}>
        Trusted projects may manage their command allowances in .coworker/config.toml.
      </div>
      {workspaces === null ? (
        <div className="text-[12px] text-muted mt-3">Loading…</div>
      ) : workspaces.length === 0 ? (
        <div className="text-[12px] text-muted mt-3">No workspaces are trusted.</div>
      ) : (
        <div className="mt-3 divide-y divide-border">
          {workspaces.map((workspace) => (
            <div key={workspace.workspace} className="py-2.5 flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] text-fg break-all">{workspace.workspace}</div>
                <div className="text-[11.5px] text-muted mt-0.5">
                  {workspace.requested_commands.length
                    ? `${workspace.requested_commands.length} project command allowance${workspace.requested_commands.length === 1 ? "" : "s"}`
                    : "No project command allowances currently declared"}
                  {!workspace.exists ? " · Folder unavailable" : ""}
                </div>
              </div>
              <button
                className="text-[12px] text-danger px-2 py-1"
                onClick={() => void revoke(workspace.workspace)}
              >
                Revoke
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function UpdateInline() {
  const [state, setState] = useState<"idle" | "checking" | "none" | "found" | "installing" | "error">("idle");
  const [version, setVersion] = useState("");

  const check = async () => {
    setState("checking");
    try {
      const u = await checkForUpdate();
      if (u) {
        setVersion(u.version);
        setState("found");
      } else {
        setState("none");
      }
    } catch {
      setState("error");
    }
  };

  const install = async () => {
    setState("installing");
    try {
      await installUpdate();
    } catch {
      setState("error");
    }
  };

  return (
    <span className="inline-flex items-center gap-2.5">
      {state === "found" ? (
        <button className={BTN_BORDERED} onClick={install} data-testid="settings-update-install">
          Update to v{version} and restart
        </button>
      ) : (
        <button
          className={BTN_BORDERED}
          onClick={check}
          disabled={state === "checking" || state === "installing"}
          data-testid="settings-update-check"
        >
          {state === "checking" ? "Checking…" : "Check for updates"}
        </button>
      )}
      {(state === "none" || state === "error" || state === "installing") && (
        <span className="text-[12px] text-muted">
          {state === "none"
            ? "You're on the latest version."
            : state === "error"
              ? "Couldn't check right now — try again later."
              : "Downloading — OpenWorker restarts by itself when it's ready."}
        </span>
      )}
    </span>
  );
}

function ContextBarCard() {
  const [shown, setShown] = useState<boolean | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setShown(s.context_bar === true))
      .catch(() => setShown(false));
  }, []);

  const save = async (next: boolean) => {
    setShown(next);
    await setContextBar(next);
  };

  if (shown === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="context-bar-card">
      <div className={FIELD_LABEL}>Composer</div>
      <label className="flex items-start gap-3 py-2 cursor-pointer">
        <input
          type="checkbox"
          className="mt-0.5 accent-accent"
          data-testid="context-bar-toggle"
          checked={shown}
          onChange={(e) => save(e.target.checked)}
        />
        <span>
          <span className="block text-[13px] text-fg">Show the context window bar</span>
          <span className="block text-[12px] text-muted">
            A small meter showing how full the model&rsquo;s context window is.
          </span>
        </span>
      </label>
    </div>
  );
}

function SidebarCard() {
  const [peek, setPeek] = useState<number | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setPeek(s.sessions_peek || 5))
      .catch(() => setPeek(5));
  }, []);

  const save = async (n: number) => {
    const clamped = Math.max(1, Math.min(n || 5, 50));
    setPeek(clamped);
    await setSessionsPeek(clamped);
  };

  if (peek === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>Sidebar</div>
      <label className="flex items-center gap-3 mt-2.5">
        <span className="text-[13px] text-fg">Conversations shown per coworker</span>
        <input
          type="number"
          min={1}
          max={50}
          value={peek}
          className="w-16 px-2 py-1.5 rounded-md border border-border bg-bg text-[13px] text-fg outline-none focus:border-accent"
          onChange={(e) => save(Number(e.target.value))}
        />
      </label>
      <div className={FIELD_HELP}>
        Longer lists collapse behind &ldquo;Show more&rdquo;. Applies per coworker and per project.
      </div>
    </div>
  );
}

function FilesCard() {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [scratchDraft, setScratchDraft] = useState("");
  const [scratchMsg, setScratchMsg] = useState<string | null>(null);
  const desktop = isTauri();

  const refresh = () =>
    getSettings()
      .then((s) => {
        setSettings(s);
        setScratchDraft((d) => d || s.scratch_base || "");
      })
      .catch(() => setSettings(null));

  useEffect(() => {
    refresh();
  }, []);

  const saveScratch = async () => {
    setScratchMsg(null);
    const res = await setScratchBase(scratchDraft.trim());
    if (res.ok) {
      setScratchMsg("Saved. New conversations will use this location.");
      refresh();
    } else {
      setScratchMsg(res.error || "Could not use that location.");
    }
  };

  const browseScratch = async () => {
    const picked = await pickFolder();
    if (picked) setScratchDraft(picked);
  };

  if (!settings) return null;

  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>Files</div>
      <div className="flex items-center gap-2 mt-2.5">
        <input
          className={INPUT}
          type="text"
          placeholder="~/OpenWorker"
          value={scratchDraft}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => setScratchDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && saveScratch()}
        />
        {desktop && (
          <button className={BTN_BORDERED} onClick={browseScratch} title="Pick a folder">
            Browse
          </button>
        )}
        <button className={BTN_ACCENT} onClick={saveScratch} disabled={!scratchDraft.trim()}>
          Save
        </button>
      </div>
      <div className={FIELD_HELP}>
        Each conversation gets its own folder under this location.
      </div>
      {scratchMsg && <div className="text-[12.5px] text-muted mt-2.5">{scratchMsg}</div>}
    </div>
  );
}
