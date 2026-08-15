import { useEffect, useState } from "react";

export type UiStyle = "default" | "glassmorphism" | "liquid-glass";

export function isPremiumUiStyle(style: UiStyle): boolean {
  return style === "glassmorphism" || style === "liquid-glass";
}

export type PresetTheme =
  | "dark"
  | "light"
  | "copper"
  | "cyberpunk"
  | "retrowave"
  | "midnight"
  | "paper"
  | "claude"
  | "auto";

export interface ThemeColors {
  bg: string;
  fg: string;
  panel: string;
  border: string;
  red: string;
  accent: string;
}

export const THEMES: Record<string, ThemeColors> = {
  copper: { bg: "#1c1410", fg: "#e8c39e", panel: "#140f0a", border: "#7a5533", red: "#d4764e", accent: "#d4764e" },
  dark: { bg: "#282c34", fg: "#9cdef2", panel: "#111111", border: "#355a66", red: "#e06c75", accent: "#d4764e" },
  light: { bg: "#f0ebe3", fg: "#5a5248", panel: "#faf6f0", border: "#d4cdc2", red: "#c47d5a", accent: "#d4764e" },
  midnight: { bg: "#0d1117", fg: "#c9d1d9", panel: "#161b22", border: "#30363d", red: "#f85149", accent: "#d4764e" },
  paper: { bg: "#faf8f5", fg: "#3b3836", panel: "#ffffff", border: "#d5d0c8", red: "#c5ac4a", accent: "#d4764e" },
  cyberpunk: { bg: "#0a0a0f", fg: "#0ff0fc", panel: "#12101a", border: "#9b30ff", red: "#e040fb", accent: "#0ff0fc" },
  retrowave: { bg: "#1a1a2e", fg: "#e94560", panel: "#16213e", border: "#533483", red: "#e94560", accent: "#e94560" },
  claude: { bg: "#262624", fg: "#f5f4f0", panel: "#30302e", border: "#4a4a47", red: "#c6613f", accent: "#c6613f" },
};

const KEY = "openwork-theme";
const UI_STYLE_KEY = "openwork-ui-style";
const PREF_EVENT = "openwork:theme-pref";
const UI_STYLE_EVENT = "openwork:ui-style-pref";
const media = window.matchMedia?.("(prefers-color-scheme: dark)");

const GLASS_TOKEN_KEYS = [
  "--glass-background",
  "--glass-background-hover",
  "--glass-background-active",
  "--glass-elevated-background",
  "--glass-elevated-background-hover",
  "--glass-floating-background",
  "--glass-border",
  "--glass-border-hover",
  "--glass-border-focus",
  "--glass-shadow",
  "--glass-shadow-elevated",
  "--glass-shadow-floating",
  "--glass-blur",
  "--glass-blur-strong",
  "--glass-opacity",
  "--glass-highlight",
  "--glass-scrim",
  "--glass-ambient-1",
  "--glass-ambient-2",
  "--glass-ambient-3",
  "--glass-saturate",
  "--glass-page-bg",
  "--glass-hero-a",
  "--glass-hero-b",
  "--glass-hero-c",
  "--radius-sm",
  "--radius-input",
  "--radius-card",
  "--radius-composer",
  "--radius-modal",
] as const;

const GLASS_OVERRIDE_KEYS = [
  "--bg",
  "--fg",
  "--panel",
  "--border",
  "--color-muted",
  "--color-muted-alt",
  "--color-accent",
  "--accent",
  "--accent-soft",
] as const;

const LG_TOKEN_KEYS = [
  "--lg-bg",
  "--lg-bg-subtle",
  "--lg-bg-strong",
  "--lg-surface",
  "--lg-surface-hover",
  "--lg-surface-active",
  "--lg-surface-elevated",
  "--lg-surface-elevated-hover",
  "--lg-surface-floating",
  "--lg-border",
  "--lg-border-strong",
  "--lg-border-focus",
  "--lg-highlight",
  "--lg-highlight-soft",
  "--lg-shadow",
  "--lg-shadow-soft",
  "--lg-shadow-deep",
  "--lg-shadow-float",
  "--lg-blur",
  "--lg-blur-heavy",
  "--lg-saturate",
  "--lg-radius-sm",
  "--lg-radius-md",
  "--lg-radius-lg",
  "--lg-radius-xl",
  "--lg-radius-pill",
  "--lg-text-primary",
  "--lg-text-secondary",
  "--lg-text-muted",
  "--lg-accent",
  "--lg-accent-soft",
  "--lg-transition-fast",
  "--lg-transition-normal",
  "--lg-transition-slow",
  "--lg-filter",
  "--lg-page-bg",
  "--lg-ambient-1",
  "--lg-ambient-2",
  "--lg-ambient-3",
  "--lg-scrim",
  "--lg-hero-a",
  "--lg-hero-b",
  "--lg-hero-c",
  "--lg-specular",
] as const;

const LG_OVERRIDE_KEYS = GLASS_OVERRIDE_KEYS;

function applyThemeColors(theme: ThemeColors) {
  const s = document.documentElement.style;
  s.setProperty("--bg", theme.bg);
  s.setProperty("--fg", theme.fg);
  s.setProperty("--panel", theme.panel);
  s.setProperty("--border", theme.border);
  s.setProperty("--red", theme.red);
  s.setProperty("--color-accent", theme.accent);
  s.setProperty("--accent", theme.accent);
  s.setProperty("--accent-soft", `color-mix(in srgb, ${theme.accent} 20%, transparent)`);
}

function clearGlassOverrides() {
  for (const key of GLASS_OVERRIDE_KEYS) {
    document.documentElement.style.removeProperty(key);
  }
}

function clearLiquidGlassOverrides() {
  for (const key of LG_OVERRIDE_KEYS) {
    document.documentElement.style.removeProperty(key);
  }
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  if (h.length === 3) {
    return [
      parseInt(h[0] + h[0], 16),
      parseInt(h[1] + h[1], 16),
      parseInt(h[2] + h[2], 16),
    ];
  }
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function isLightBg(hex: string): boolean {
  const [r, g, b] = hexToRgb(hex);
  return (r * 299 + g * 587 + b * 114) / 1000 > 128;
}

function applyGlassSemanticOverrides(theme: ThemeColors, light: boolean, border: string) {
  const s = document.documentElement.style;
  s.setProperty("--border", border);
  if (light) {
    s.setProperty("--bg", "#F8FAFC");
    s.setProperty("--fg", "#202124");
    s.setProperty("--panel", "rgba(255, 255, 255, 0.72)");
    s.setProperty("--color-muted", "#6B7280");
    s.setProperty("--color-muted-alt", "#9CA3AF");
    s.setProperty("--color-accent", "#6366F1");
    s.setProperty("--accent", "#6366F1");
    s.setProperty("--accent-soft", "color-mix(in srgb, #6366F1 20%, transparent)");
  } else {
    s.setProperty("--border", border);
    s.setProperty("--color-accent", theme.accent);
    s.setProperty("--accent", theme.accent);
    s.setProperty("--accent-soft", `color-mix(in srgb, ${theme.accent} 20%, transparent)`);
  }
}

function applyGlassTokens(theme: ThemeColors) {
  const light = isLightBg(theme.bg);
  const [pr, pg, pb] = hexToRgb(theme.panel);
  const [fr, fg, fb] = hexToRgb(theme.fg);
  const s = document.documentElement.style;
  let glassBorder: string;
  let glassBorderHover: string;

  if (light) {
    glassBorder = "rgba(148, 163, 184, 0.16)";
    glassBorderHover = "rgba(148, 163, 184, 0.28)";
    s.setProperty("--glass-page-bg", "#F8FAFC");
    s.setProperty("--glass-background", "rgba(255, 255, 255, 0.65)");
    s.setProperty("--glass-background-hover", "rgba(255, 255, 255, 0.78)");
    s.setProperty(
      "--glass-background-active",
      `color-mix(in srgb, ${theme.accent} 12%, rgba(255, 255, 255, 0.72))`,
    );
    s.setProperty("--glass-elevated-background", "rgba(255, 255, 255, 0.72)");
    s.setProperty("--glass-elevated-background-hover", "rgba(255, 255, 255, 0.82)");
    s.setProperty("--glass-floating-background", "rgba(255, 255, 255, 0.78)");
    s.setProperty("--glass-border", glassBorder);
    s.setProperty("--glass-border-hover", glassBorderHover);
    s.setProperty("--glass-border-focus", "rgba(99, 102, 241, 0.35)");
    s.setProperty(
      "--glass-shadow",
      "0 8px 30px rgba(80, 90, 140, 0.06), inset 0 1px 0 rgba(255,255,255,0.7)",
    );
    s.setProperty(
      "--glass-shadow-elevated",
      "0 8px 30px rgba(15, 23, 42, 0.05), inset 0 1px 0 rgba(255,255,255,0.7)",
    );
    s.setProperty(
      "--glass-shadow-floating",
      "0 12px 40px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255,255,255,0.75)",
    );
    s.setProperty("--glass-ambient-1", "rgba(129, 140, 248, 0.08)");
    s.setProperty("--glass-ambient-2", "rgba(96, 165, 250, 0.05)");
    s.setProperty("--glass-ambient-3", "rgba(103, 232, 249, 0.04)");
  } else {
    const base = 0.55;
    const elevated = 0.65;
    const floating = 0.78;
    glassBorder = `rgba(${fr}, ${fg}, ${fb}, 0.12)`;
    glassBorderHover = `rgba(${fr}, ${fg}, ${fb}, 0.2)`;
    s.setProperty("--glass-page-bg", theme.bg);
    s.setProperty("--glass-background", `rgba(${pr}, ${pg}, ${pb}, ${base})`);
    s.setProperty("--glass-background-hover", `rgba(${pr}, ${pg}, ${pb}, ${Math.min(base + 0.08, 0.95)})`);
    s.setProperty(
      "--glass-background-active",
      `color-mix(in srgb, ${theme.accent} 18%, rgba(${pr}, ${pg}, ${pb}, ${base}))`,
    );
    s.setProperty("--glass-elevated-background", `rgba(${pr}, ${pg}, ${pb}, ${elevated})`);
    s.setProperty(
      "--glass-elevated-background-hover",
      `rgba(${pr}, ${pg}, ${pb}, ${Math.min(elevated + 0.06, 0.96)})`,
    );
    s.setProperty("--glass-floating-background", `rgba(${pr}, ${pg}, ${pb}, ${floating})`);
    s.setProperty("--glass-border", glassBorder);
    s.setProperty("--glass-border-hover", glassBorderHover);
    s.setProperty(
      "--glass-border-focus",
      `color-mix(in srgb, ${theme.accent} 55%, rgba(${fr}, ${fg}, ${fb}, 0.2))`,
    );
    s.setProperty(
      "--glass-shadow",
      "0 4px 20px rgba(0,0,0,0.16), 0 1px 2px rgba(0,0,0,0.1)",
    );
    s.setProperty(
      "--glass-shadow-elevated",
      "0 6px 28px rgba(0,0,0,0.2), 0 2px 4px rgba(0,0,0,0.12)",
    );
    s.setProperty(
      "--glass-shadow-floating",
      "0 12px 40px rgba(0,0,0,0.28), 0 4px 8px rgba(0,0,0,0.14)",
    );
    s.setProperty("--glass-ambient-1", `color-mix(in srgb, ${theme.accent} 9%, transparent)`);
    s.setProperty("--glass-ambient-2", `color-mix(in srgb, ${theme.accent} 5%, transparent)`);
    s.setProperty("--glass-ambient-3", `color-mix(in srgb, ${theme.accent} 3%, transparent)`);
  }

  s.setProperty("--glass-blur", "24px");
  s.setProperty("--glass-blur-strong", "24px");
  s.setProperty("--glass-saturate", "140%");
  s.setProperty("--glass-opacity", light ? "0.65" : "0.55");
  s.setProperty(
    "--glass-highlight",
    light ? "inset 0 1px 0 rgba(255,255,255,0.7)" : "inset 0 1px 0 rgba(255,255,255,0.06)",
  );
  s.setProperty("--glass-scrim", light ? "rgba(15, 23, 42, 0.32)" : "rgba(0, 0, 0, 0.48)");
  s.setProperty("--glass-hero-a", light ? "#818CF8" : theme.accent);
  s.setProperty(
    "--glass-hero-b",
    light ? "#A78BFA" : `color-mix(in srgb, ${theme.accent} 75%, #A78BFA)`,
  );
  s.setProperty(
    "--glass-hero-c",
    light ? "#67E8F9" : `color-mix(in srgb, ${theme.accent} 45%, #67E8F9)`,
  );
  s.setProperty("--radius-sm", "clamp(8px, 0.7vw, 10px)");
  s.setProperty("--radius-input", "clamp(8px, 0.85vw, 12px)");
  s.setProperty("--radius-card", light ? "clamp(12px, 1.2vw, 20px)" : "clamp(12px, 1vw, 16px)");
  s.setProperty("--radius-composer", light ? "clamp(16px, 1.6vw, 24px)" : "clamp(14px, 1.4vw, 20px)");
  s.setProperty("--radius-modal", light ? "clamp(14px, 1.4vw, 20px)" : "clamp(12px, 1.2vw, 18px)");
  applyGlassSemanticOverrides(theme, light, glassBorder);
}

function clearGlassTokens() {
  for (const key of GLASS_TOKEN_KEYS) {
    document.documentElement.style.removeProperty(key);
  }
  clearGlassOverrides();
}

function clearLiquidGlassTokens() {
  for (const key of LG_TOKEN_KEYS) {
    document.documentElement.style.removeProperty(key);
  }
  clearLiquidGlassOverrides();
}

function applyLiquidGlassSemanticOverrides(theme: ThemeColors, light: boolean, border: string) {
  const s = document.documentElement.style;
  s.setProperty("--border", border);
  s.setProperty("--lg-text-primary", light ? "#1a1a1e" : theme.fg);
  s.setProperty("--lg-text-secondary", light ? "#4b5563" : `color-mix(in srgb, ${theme.fg} 78%, transparent)`);
  s.setProperty("--lg-text-muted", light ? "#6b7280" : `color-mix(in srgb, ${theme.fg} 52%, transparent)`);
  if (light) {
    s.setProperty("--bg", "#eef1f6");
    s.setProperty("--fg", "#1a1a1e");
    s.setProperty("--panel", "rgba(255, 255, 255, 0.55)");
    s.setProperty("--color-muted", "#6b7280");
    s.setProperty("--color-muted-alt", "#9ca3af");
  } else {
    s.setProperty("--color-accent", theme.accent);
    s.setProperty("--accent", theme.accent);
    s.setProperty("--accent-soft", `color-mix(in srgb, ${theme.accent} 18%, transparent)`);
  }
  s.setProperty("--lg-accent", theme.accent);
  s.setProperty("--lg-accent-soft", `color-mix(in srgb, ${theme.accent} 22%, transparent)`);
}

function applyLiquidGlassTokens(theme: ThemeColors) {
  const light = isLightBg(theme.bg);
  const [pr, pg, pb] = hexToRgb(theme.panel);
  const [fr, fg, fb] = hexToRgb(theme.fg);
  const [br, bg, bb] = hexToRgb(theme.bg);
  const s = document.documentElement.style;
  let lgBorder: string;
  let lgBorderStrong: string;
  let lgBorderFocus: string;

  s.setProperty("--lg-transition-fast", "140ms");
  s.setProperty("--lg-transition-normal", "200ms");
  s.setProperty("--lg-transition-slow", "280ms");
  s.setProperty("--lg-radius-sm", "clamp(8px, 0.65vw, 10px)");
  s.setProperty("--lg-radius-md", "clamp(10px, 0.85vw, 12px)");
  s.setProperty("--lg-radius-lg", light ? "clamp(14px, 1.2vw, 18px)" : "clamp(12px, 1vw, 16px)");
  s.setProperty("--lg-radius-xl", light ? "clamp(16px, 1.5vw, 22px)" : "clamp(14px, 1.3vw, 20px)");
  s.setProperty("--lg-radius-pill", "999px");
  s.setProperty("--lg-blur", "20px");
  s.setProperty("--lg-blur-heavy", "32px");
  s.setProperty("--lg-saturate", "165%");
  s.setProperty("--lg-filter", "blur(var(--lg-blur)) saturate(var(--lg-saturate))");
  s.setProperty(
    "--lg-specular",
    light ? "inset 0 1px 0 rgba(255,255,255,0.65)" : "inset 0 1px 0 rgba(255,255,255,0.08)",
  );

  if (light) {
    lgBorder = "rgba(255, 255, 255, 0.55)";
    lgBorderStrong = "rgba(148, 163, 184, 0.28)";
    lgBorderFocus = `color-mix(in srgb, ${theme.accent} 42%, rgba(148, 163, 184, 0.35))`;
    s.setProperty("--lg-page-bg", "#eef1f6");
    s.setProperty("--lg-bg", "#eef1f6");
    s.setProperty("--lg-bg-subtle", `rgba(${br}, ${bg}, ${bb}, 0.4)`);
    s.setProperty("--lg-bg-strong", `rgba(${pr}, ${pg}, ${pb}, 0.72)`);
    s.setProperty("--lg-surface", "rgba(255, 255, 255, 0.52)");
    s.setProperty("--lg-surface-hover", "rgba(255, 255, 255, 0.68)");
    s.setProperty(
      "--lg-surface-active",
      `color-mix(in srgb, ${theme.accent} 14%, rgba(255, 255, 255, 0.62))`,
    );
    s.setProperty("--lg-surface-elevated", "rgba(255, 255, 255, 0.68)");
    s.setProperty("--lg-surface-elevated-hover", "rgba(255, 255, 255, 0.78)");
    s.setProperty("--lg-surface-floating", "rgba(255, 255, 255, 0.82)");
    s.setProperty("--lg-shadow-soft", "0 2px 8px rgba(15, 23, 42, 0.04)");
    s.setProperty("--lg-shadow", "0 8px 28px rgba(15, 23, 42, 0.06), var(--lg-specular)");
    s.setProperty("--lg-shadow-deep", "0 12px 36px rgba(15, 23, 42, 0.1), var(--lg-specular)");
    s.setProperty("--lg-shadow-float", "0 18px 48px rgba(15, 23, 42, 0.12), var(--lg-specular)");
    s.setProperty("--lg-ambient-1", `color-mix(in srgb, ${theme.accent} 10%, transparent)`);
    s.setProperty("--lg-ambient-2", "rgba(147, 197, 253, 0.08)");
    s.setProperty("--lg-ambient-3", "rgba(196, 181, 253, 0.06)");
    s.setProperty("--lg-scrim", "rgba(15, 23, 42, 0.28)");
    s.setProperty("--lg-hero-a", theme.accent);
    s.setProperty("--lg-hero-b", `color-mix(in srgb, ${theme.accent} 70%, #a78bfa)`);
    s.setProperty("--lg-hero-c", `color-mix(in srgb, ${theme.accent} 40%, #67e8f9)`);
  } else {
    lgBorder = `rgba(${fr}, ${fg}, ${fb}, 0.1)`;
    lgBorderStrong = `rgba(${fr}, ${fg}, ${fb}, 0.18)`;
    lgBorderFocus = `color-mix(in srgb, ${theme.accent} 48%, rgba(${fr}, ${fg}, ${fb}, 0.16))`;
    s.setProperty("--lg-page-bg", theme.bg);
    s.setProperty("--lg-bg", theme.bg);
    s.setProperty("--lg-bg-subtle", `rgba(${br}, ${bg}, ${bb}, 0.55)`);
    s.setProperty("--lg-bg-strong", `rgba(${pr}, ${pg}, ${pb}, 0.78)`);
    s.setProperty("--lg-surface", `rgba(${pr}, ${pg}, ${pb}, 0.48)`);
    s.setProperty("--lg-surface-hover", `rgba(${pr}, ${pg}, ${pb}, 0.58)`);
    s.setProperty(
      "--lg-surface-active",
      `color-mix(in srgb, ${theme.accent} 16%, rgba(${pr}, ${pg}, ${pb}, 0.56))`,
    );
    s.setProperty("--lg-surface-elevated", `rgba(${pr}, ${pg}, ${pb}, 0.62)`);
    s.setProperty("--lg-surface-elevated-hover", `rgba(${pr}, ${pg}, ${pb}, 0.72)`);
    s.setProperty("--lg-surface-floating", `rgba(${pr}, ${pg}, ${pb}, 0.78)`);
    s.setProperty("--lg-shadow-soft", "0 2px 10px rgba(0, 0, 0, 0.12)");
    s.setProperty("--lg-shadow", "0 8px 28px rgba(0, 0, 0, 0.18), var(--lg-specular)");
    s.setProperty("--lg-shadow-deep", "0 14px 40px rgba(0, 0, 0, 0.24), var(--lg-specular)");
    s.setProperty("--lg-shadow-float", "0 20px 52px rgba(0, 0, 0, 0.32), var(--lg-specular)");
    s.setProperty("--lg-ambient-1", `color-mix(in srgb, ${theme.accent} 8%, transparent)`);
    s.setProperty("--lg-ambient-2", `color-mix(in srgb, ${theme.accent} 5%, transparent)`);
    s.setProperty("--lg-ambient-3", `color-mix(in srgb, ${theme.accent} 3%, transparent)`);
    s.setProperty("--lg-scrim", "rgba(0, 0, 0, 0.45)");
    s.setProperty("--lg-hero-a", theme.accent);
    s.setProperty("--lg-hero-b", `color-mix(in srgb, ${theme.accent} 72%, #a78bfa)`);
    s.setProperty("--lg-hero-c", `color-mix(in srgb, ${theme.accent} 42%, #67e8f9)`);
  }

  s.setProperty("--lg-border", lgBorder);
  s.setProperty("--lg-border-strong", lgBorderStrong);
  s.setProperty("--lg-border-focus", lgBorderFocus);
  s.setProperty("--lg-highlight", light ? "rgba(255,255,255,0.55)" : "rgba(255,255,255,0.1)");
  s.setProperty("--lg-highlight-soft", light ? "rgba(255,255,255,0.28)" : "rgba(255,255,255,0.04)");
  applyLiquidGlassSemanticOverrides(theme, light, lgBorder);
}

function applyUiStyle(style: UiStyle, theme?: ThemeColors) {
  clearGlassTokens();
  clearLiquidGlassTokens();

  if (style === "glassmorphism") {
    document.documentElement.dataset.uiStyle = "glassmorphism";
    if (theme) applyGlassTokens(theme);
    return;
  }

  if (style === "liquid-glass") {
    document.documentElement.dataset.uiStyle = "liquid-glass";
    if (theme) applyLiquidGlassTokens(theme);
    return;
  }

  delete document.documentElement.dataset.uiStyle;
  if (theme) applyThemeColors(theme);
}

export function getUiStylePref(): UiStyle {
  try {
    const v = localStorage.getItem(UI_STYLE_KEY);
    if (v === "glassmorphism") return "glassmorphism";
    if (v === "liquid-glass") return "liquid-glass";
    return "default";
  } catch {
    return "default";
  }
}

export function setUiStylePref(style: UiStyle) {
  try {
    if (style === "default") localStorage.removeItem(UI_STYLE_KEY);
    else localStorage.setItem(UI_STYLE_KEY, style);
  } catch {}
  const chosenKey = getThemePref() === "auto" ? (media?.matches ? "copper" : "light") : getThemePref();
  const theme = THEMES[chosenKey] || THEMES.copper;
  applyUiStyle(style, theme);
  window.dispatchEvent(new CustomEvent(UI_STYLE_EVENT));
}

export function initUiStyle() {
  const chosenKey = getThemePref() === "auto" ? (media?.matches ? "copper" : "light") : getThemePref();
  const theme = THEMES[chosenKey] || THEMES.copper;
  applyUiStyle(getUiStylePref(), theme);
}

export function useUiStylePref(): [UiStyle, (s: UiStyle) => void] {
  const [pref, setPref] = useState<UiStyle>(getUiStylePref);
  useEffect(() => {
    const sync = () => setPref(getUiStylePref());
    window.addEventListener(UI_STYLE_EVENT, sync);
    window.addEventListener(PREF_EVENT, sync);
    return () => {
      window.removeEventListener(UI_STYLE_EVENT, sync);
      window.removeEventListener(PREF_EVENT, sync);
    };
  }, []);
  return [pref, setUiStylePref];
}

export function getThemePref(): PresetTheme {
  try {
    const v = localStorage.getItem(KEY) as PresetTheme | null;
    return v && (THEMES[v] || v === "light" || v === "dark" || v === "auto") ? v : "copper";
  } catch {
    return "copper";
  }
}

function apply(pref: PresetTheme) {
  const chosenKey = pref === "auto" ? (media?.matches ? "copper" : "light") : pref;
  const theme = THEMES[chosenKey] || THEMES.copper;

  document.documentElement.dataset.theme = chosenKey;
  applyThemeColors(theme);
  applyUiStyle(getUiStylePref(), theme);
}

export function setThemePref(pref: PresetTheme) {
  try {
    if (pref === "auto") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, pref);
  } catch {}
  apply(pref);
  window.dispatchEvent(new CustomEvent(PREF_EVENT));
}

export function initTheme() {
  apply(getThemePref());
  media?.addEventListener("change", () => {
    if (getThemePref() === "auto") apply("auto");
  });
}

export function useThemePref(): [PresetTheme, (p: PresetTheme) => void] {
  const [pref, setPref] = useState<PresetTheme>(getThemePref);
  useEffect(() => {
    const sync = () => setPref(getThemePref());
    window.addEventListener(PREF_EVENT, sync);
    return () => window.removeEventListener(PREF_EVENT, sync);
  }, []);
  return [pref, setThemePref];
}
