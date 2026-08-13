export function WaitingForAgent({ label }: { label?: string }) {
  return (
    <div className="waiting-transcript py-2 px-3">
      <div className="waiting-row flex items-center gap-2 text-[13px] text-accent font-mono" aria-live="polite">
        <span className="waiting-spinner w-3.5 h-3.5 border-2 border-accent border-t-transparent rounded-full animate-spin shrink-0" />
        <span>{label || "Waiting for agent..."}</span>
      </div>
    </div>
  );
}
