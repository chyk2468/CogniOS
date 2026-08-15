import { useLayoutEffect, useRef, useState } from "react";
import type { UiStyle } from "../../theme";
import { useUiStylePref } from "../../theme";

const OPTIONS: { value: UiStyle; label: string }[] = [
  { value: "default", label: "Standard" },
  { value: "glassmorphism", label: "Glassmorphism" },
  { value: "liquid-glass", label: "Liquid Glass" },
];

export function UiStyleSegmentedControl({
  value,
  onChange,
}: {
  value: UiStyle;
  onChange: (s: UiStyle) => void;
}) {
  const [activeUiStyle] = useUiStylePref();
  const containerRef = useRef<HTMLDivElement>(null);
  const [indicator, setIndicator] = useState({ left: 0, width: 0 });
  const lg = activeUiStyle === "liquid-glass";

  const measure = () => {
    const root = containerRef.current;
    if (!root) return;
    const btn = root.querySelector<HTMLElement>(`[data-ui-style-value="${value}"]`);
    if (!btn) return;
    setIndicator({ left: btn.offsetLeft, width: btn.offsetWidth });
  };

  useLayoutEffect(() => {
    measure();
    const root = containerRef.current;
    if (!root) return;
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    return () => ro.disconnect();
  }, [value, lg]);

  return (
    <div
      ref={containerRef}
      className={
        "seg mt-2.5 flex flex-wrap gap-1 p-1 rounded-md border border-border relative " +
        (lg ? "lg-seg ui-style-seg" : "bg-bg")
      }
      role="radiogroup"
      aria-label="UI Style"
    >
      {lg && (
        <span
          className="lg-seg-indicator"
          aria-hidden
          style={{
            width: indicator.width,
            transform: `translateX(${indicator.left}px)`,
          }}
        />
      )}
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="radio"
          aria-checked={value === opt.value}
          data-ui-style-value={opt.value}
          className={
            "relative z-[1] px-2.5 py-1 rounded-md text-[12px] transition-colors " +
            (value === opt.value
              ? lg
                ? "text-fg font-semibold"
                : "bg-panel text-accent font-semibold shadow-sm border border-accent/40"
              : "text-muted hover:text-fg")
          }
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
