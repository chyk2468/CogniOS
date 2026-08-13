import { useEffect, useState } from "react";

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
const PREF_EVENT = "openwork:theme-pref";
const media = window.matchMedia?.("(prefers-color-scheme: dark)");

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

  const s = document.documentElement.style;
  document.documentElement.dataset.theme = chosenKey;

  s.setProperty("--bg", theme.bg);
  s.setProperty("--fg", theme.fg);
  s.setProperty("--panel", theme.panel);
  s.setProperty("--border", theme.border);
  s.setProperty("--red", theme.red);
  s.setProperty("--color-accent", theme.accent);
  s.setProperty("--accent", theme.accent);
  s.setProperty("--accent-soft", `color-mix(in srgb, ${theme.accent} 20%, transparent)`);
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
