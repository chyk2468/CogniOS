// Shared style grammar for the Connectors surfaces (UX-DECISIONS §21): macOS
// System-Settings-style grouped inset lists — quiet rows, hairline separators,
// pill buttons, small status tags. Mirrors ui-mocks/connectors-redesign.html.

/** Grouped inset list container; children separate with hairlines. */
export const GRP = "rounded-md2 border border-border bg-panel divide-y divide-line overflow-hidden";

/** One list row: 44px minimum, comfortable gaps. */
export const ROW = "flex items-center gap-3 px-4 py-2.5 min-h-[44px]";

/** Sentence-case section header above a group. */
export const GRP_H = "text-[12px] font-semibold text-muted px-4 mt-6 mb-1.5";

/** Quiet footnote under a group. */
export const FOOT = "text-[12px] text-faint px-4 pt-1.5";

export const PILL_ACCENT =
  "text-[12.5px] font-medium px-3 py-1.5 rounded-md bg-accent text-white shrink-0 disabled:opacity-50";
export const PILL_QUIET =
  "text-[12.5px] font-medium px-3 py-1.5 rounded-md bg-bg border border-border text-accent shrink-0 hover:border-border";
export const PILL_LINE =
  "text-[12.5px] font-medium px-3 py-1.5 rounded-md border border-border text-fg shrink-0 hover:bg-bg";

export const TAG_ACCENT =
  "text-[10.5px] font-semibold px-1.5 py-0.5 rounded bg-accentSoft text-accent shrink-0";
export const TAG_WARN =
  "text-[10.5px] font-semibold px-1.5 py-0.5 rounded bg-warnSoft text-warnInk shrink-0";
export const TAG_QUIET =
  "text-[10.5px] font-semibold px-1.5 py-0.5 rounded bg-bg border border-border text-muted shrink-0";

/** Status chip variants for the Connected list. */
export const CHIP_OK =
  "text-[11px] font-medium px-2 py-0.5 rounded-md bg-okSoft text-ok border border-okLine shrink-0";
export const CHIP_WARN =
  "text-[11px] font-medium px-2 py-0.5 rounded-md bg-warnSoft text-warnInk border border-warnInk/20 shrink-0";
export const CHIP_OFF =
  "text-[11px] font-medium px-2 py-0.5 rounded-md bg-bg text-muted border border-border shrink-0";

/** Small × affordance (danger on hover). */
export const XBTN = "text-faint hover:text-danger shrink-0 leading-none";
