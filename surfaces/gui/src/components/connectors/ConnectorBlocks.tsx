import { useEffect, useState } from "react";
import {
  allowUser,
  connectConnector,
  connectMcpBacked,
  disallowUser,
  getSubscriptions,
  resolveUnauthorized,
  unsubscribeChannel,
  updateConnectorTools,
  type Connector,
  type Subscription,
} from "../../api";

const SEC_H = "text-[11px] uppercase tracking-[0.05em] text-faint font-semibold";
const BTN_BORDERED = "text-[12.5px] px-3 py-1.5 rounded-md border border-border bg-bg hover:border-border shrink-0";
const BTN_ACCENT = "text-[12.5px] px-3 py-1.5 rounded-md bg-accent text-white shrink-0 disabled:opacity-50";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

const relTime = (epoch?: number | null): string | null => {
  if (!epoch) return null;
  const secs = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (secs < 90) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 48) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
};

export function UnauthorizedBlock({
  c,
  onChanged,
  teamId,
}: {
  c: Connector;
  onChanged: () => void;
  teamId?: string;
}) {
  const items = (c.unauthorized ?? []).filter(
    (m) => teamId === undefined || m.team_id === teamId,
  );
  if (items.length === 0) return null;
  const act = async (id: string, action: "dismiss" | "allow" | "allow_deliver") => {
    await resolveUnauthorized(c.name, id, action);
    onChanged();
  };
  return (
    <div
      className="border-t border-border px-3.5 py-3"
      data-testid={teamId ? `unauthorized-${c.name}-${teamId}` : `unauthorized-${c.name}`}
    >
      <div className={SEC_H + " mb-2"}>
        Messages from senders you haven't allowed · {items.length}
      </div>
      <div className="space-y-2">
        {items.map((m) => (
          <div key={m.id} className="rounded-md border border-border bg-bg p-2.5">
            <div className="flex items-center gap-2 text-[12px] text-muted">
              <span className="font-medium text-fg">{m.user_name || m.user_id}</span>
              <span>in {m.chat_name || m.chat_id}</span>
              <span className="ml-auto shrink-0">{relTime(m.ts) || ""}</span>
            </div>
            <div className="text-[12.5px] mt-1 break-words">{m.text}</div>
            <div className="flex items-center gap-1.5 mt-2">
              <button
                className="text-[11.5px] px-2 py-1 rounded-md bg-accent text-white"
                data-testid={`parked-allow-deliver-${m.id}`}
                title="Add the sender to the allow-list and deliver this message now"
                onClick={() => act(m.id, "allow_deliver")}
              >
                Allow & deliver
              </button>
              <button
                className={BTN_BORDERED}
                data-testid={`parked-allow-${m.id}`}
                title="Add the sender to the allow-list; this message is discarded"
                onClick={() => act(m.id, "allow")}
              >
                Allow only
              </button>
              <button
                className="text-[11.5px] px-2 py-1 rounded-md text-faint hover:text-danger"
                data-testid={`parked-dismiss-${m.id}`}
                title="Throw this message away"
                onClick={() => act(m.id, "dismiss")}
              >
                Dismiss
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ListeningSessionsBlock({ c }: { c: Connector }) {
  const [subs, setSubs] = useState<Subscription[] | null>(null);
  const load = () => getSubscriptions().then(setSubs).catch(() => setSubs([]));
  useEffect(() => {
    load();
  }, [c.name]);
  const platformOf = (channel: string) =>
    channel.includes(":") ? channel.split(":")[0] : "slack";
  const mine = (subs ?? []).filter((s) => platformOf(s.channel) === c.name);
  return (
    <div className="border-t border-border px-3.5 py-3" data-testid={`listening-${c.name}`}>
      <div className={SEC_H + " mb-2"}>Sessions listening to {c.title} channels · {mine.length}</div>
      {mine.length === 0 ? (
        <div className="text-[12px] text-faint">
          None yet — open a session's Sources ▸ Channels to subscribe it to a channel.
        </div>
      ) : (
        <div className="space-y-1.5">
          {mine.map((s) => (
            <div className="flex items-center gap-2 text-[12.5px]" key={s.session_id + s.channel}>
              <span className="min-w-0 truncate" title={s.session_id}>
                {s.session_title || s.session_id}
                {s.agent ? <span className="text-faint"> · {s.agent}</span> : null}
              </span>
              <span className="text-muted shrink-0" title={s.channel}>
                ← {s.channel_name ? `#${s.channel_name}` : s.channel}
              </span>
              <button
                className="ml-auto text-faint hover:text-danger shrink-0"
                title="Unsubscribe this session"
                onClick={async () => {
                  await unsubscribeChannel(s.session_id, s.channel);
                  load();
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AllowlistBlock({
  c,
  onChanged,
  teamId,
  allowed,
  allowedNames,
}: {
  c: Connector;
  onChanged: () => void;
  teamId?: string;
  allowed?: string[];
  allowedNames?: Record<string, string | null>;
}) {
  const allowedUsers = allowed ?? c.allowed_users;
  const names = allowedNames ?? c.allowed_user_names;
  const recent = (c.recent ?? []).filter(
    (r) => teamId === undefined || r.team_id === teamId,
  );
  const unknownRecent = recent.filter((r) => !r.authorized);

  return (
    <div className="border-t border-border px-3.5 py-3 grid grid-cols-2 gap-5">
      <div>
        <div className={SEC_H + " mb-2"}>Allowed to message</div>
        <div className="flex flex-wrap gap-1.5">
          {allowedUsers.length === 0 && (
            <span className="text-[12px] text-faint">nobody yet — Allow a recent sender →</span>
          )}
          {allowedUsers.map((u) => (
            <span
              key={u}
              className="inline-flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-md bg-bg border border-border text-[12px]"
              title={`id ${u}`}
            >
              <span className="w-4 h-4 rounded-md bg-accentSoft text-accent grid place-items-center text-[9px] font-bold">
                {initials(names?.[u] || u)}
              </span>
              {names?.[u] || u}
              <button
                className="w-4 h-4 grid place-items-center text-faint hover:text-danger"
                title="remove"
                onClick={async () => {
                  await disallowUser(c.name, u, teamId);
                  onChanged();
                }}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      </div>
      <div>
        <div className={SEC_H + " mb-2"}>Recent senders</div>
        {unknownRecent.length === 0 ? (
          <div className="text-[12px] text-faint">None yet. Message the bot once and it'll show here.</div>
        ) : (
          <div className="space-y-1.5">
            {unknownRecent.map((r) => (
              <div className="flex items-center gap-2 text-[12.5px]" key={r.user_id}>
                <span className="w-5 h-5 rounded-md bg-bg border border-border grid place-items-center text-[9px] font-bold text-muted shrink-0">
                  {initials(r.user_name || "?")}
                </span>
                <span className="min-w-0 truncate" title={`id ${r.user_id}`}>
                  {r.user_name || "unknown"} <span className="text-faint">· {r.chat_type}</span>
                </span>
                <button
                  className="ml-auto text-[11.5px] px-2 py-0.5 rounded-md bg-accent text-white shrink-0"
                  onClick={async () => {
                    await allowUser(c.name, r.user_id, teamId);
                    onChanged();
                  }}
                >
                  Allow
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function ConnectorTools({ c, onChanged }: { c: Connector; onChanged: () => void }) {
  const toggle = async (toolName: string, enabled: boolean) => {
    await updateConnectorTools(c.name, { [toolName]: enabled });
    onChanged();
  };
  if (!c.tools?.length)
    return (
      <div className="border-t border-border px-3.5 py-3 text-[12.5px] text-muted">
        No tools for this connector yet.
      </div>
    );
  return (
    <div className="border-t border-border px-3.5 py-3">
      <div className={SEC_H + " mb-2"}>Tools exposed to CogniOS</div>
      <div className="space-y-1.5">
        {c.tools.map((tool) => (
          <label
            className="flex items-start gap-2.5 p-2 rounded-md border border-border bg-bg cursor-pointer"
            key={tool.name}
          >
            <input
              type="checkbox"
              className="mt-0.5 shrink-0 accent-accent"
              checked={tool.enabled}
              onChange={(e) => toggle(tool.name, e.target.checked)}
            />
            <span className="min-w-0">
              <span className="block text-[13px] text-fg font-medium">{tool.label}</span>
              <span className="block text-[11.5px] text-faint">
                {tool.name} · {tool.kind} · asks approval
              </span>
              <span className="block text-[11.5px] text-faint">{tool.description}</span>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

export function ConnectSetup({
  c,
  onConnected,
  manualOnly = false,
}: {
  c: Connector;
  onConnected: () => void;
  manualOnly?: boolean;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await connectConnector(c.name, values);
    setBusy(false);
    if (res.ok) onConnected();
    else setError(res.error || "could not connect");
  };



  const mcpOneClick = async () => {
    setError(null);
    const res = await connectMcpBacked(c.name);
    if (res.ok) setWaiting(true);
    else setError(res.error || "could not start the connect");
  };

  return (
    <div className="border-t border-border px-3.5 py-3 space-y-3">
      {c.mcp && !manualOnly && (
        <div className="space-y-2" data-testid="mcp-connect">
          <button className={BTN_ACCENT} onClick={mcpOneClick} disabled={waiting}>
            {waiting ? "Check your browser…" : `Connect ${c.title} with one click`}
          </button>
          {c.fields.length > 0 && (
            <div className="text-[11.5px] text-faint">or connect manually:</div>
          )}
        </div>
      )}

      {c.instructions.length > 0 && (
        <ol className="list-decimal pl-4 text-[12.5px] text-muted leading-relaxed space-y-1">
          {c.instructions.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      )}
      {c.fields.map((f) => (
        <label className="conn-field block space-y-1" key={f.key}>
          <span className="conn-field-label text-[12.5px] font-medium text-fg block">
            {f.label}
            {!f.required && <em className="text-muted font-normal"> (optional)</em>}
          </span>
          <input
            type={f.secret ? "password" : "text"}
            placeholder={f.placeholder}
            className="w-full px-3 py-1.5 rounded-md border border-border bg-bg text-[13px] text-fg outline-none focus:border-accent"
            value={values[f.key] || ""}
            spellCheck={false}
            onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
          />
          {f.help && <span className="conn-field-help text-[11.5px] text-muted block">{f.help}</span>}
        </label>
      ))}
      <div>
        <button className={BTN_ACCENT} onClick={submit} disabled={busy}>
          {busy ? "Validating…" : "Connect"}
        </button>
      </div>
      {error && <div className="text-[12.5px] text-danger">{error}</div>}
    </div>
  );
}
