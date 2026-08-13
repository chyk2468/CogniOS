import type { SessionInfo } from "../../types";
import { ConnectorIcon } from "../../connectors/ConnectorIcon";

export function AttnBadge({ n }: { n: number }) {
  if (!n) return null;
  return (
    <span
      className="text-[10px] font-semibold text-fg bg-faint/30 rounded-md px-1.5 leading-[15px] shrink-0"
      title={`${n} awaiting your attention`}
    >
      {n > 99 ? "99+" : n}
    </span>
  );
}

export function LiveDot({ state }: { state?: "working" | "sleeping" | "idle" }) {
  if (state !== "working" && state !== "sleeping") return null;
  return state === "working" ? (
    <span className="w-1.5 h-1.5 rounded-md bg-accent animate-pulse shrink-0" title="Working now" />
  ) : (
    <span
      className="w-1.5 h-1.5 rounded-md bg-faint/60 shrink-0"
      title="Sleeping (will wake itself)"
    />
  );
}

export function OriginIcon({ s }: { s: SessionInfo }) {
  if (s.origin !== "slack") return null;
  return (
    <ConnectorIcon
      connector={{ logo: "slack", brand_color: "#611f69" }}
      size={12}
      title={s.origin_label || "From Slack"}
    />
  );
}

export function ConnectorDot({ subs }: { subs?: string[] }) {
  if (!subs || subs.length === 0) return null;
  return (
    <span
      className="w-1.5 h-1.5 rounded-md bg-faint shrink-0"
      data-brand={subs[0]}
      title={subs.join(", ")}
    />
  );
}

export const compactAge = (iso?: string | null): string => {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return "now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d`;
  const weeks = Math.floor(days / 7);
  if (days < 30) return `${weeks}w`;
  const months = Math.floor(days / 30);
  if (days < 365) return `${months}mo`;
  return `${Math.floor(days / 365)}y`;
};
