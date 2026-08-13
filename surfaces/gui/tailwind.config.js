/** Tailwind config — mirrors platform/ui-mocks/redesign.html so the app can use the mock's
 *  exact utility classes. Colors map to the CSS custom properties already defined in styles.css
 *  (so light/dark theming flows through one source of truth). */
// Tokens are hex CSS vars (shared with styles.css), which Tailwind can't alpha-multiply for
// `/NN` opacity utilities. Wrap each in color-mix so `bg-panel/70` etc. work, while bare
// `var(--x)` usage in styles.css stays intact. (color-mix is supported in the Chromium webview.)
const tok = (name) => ({ opacityValue }) =>
  opacityValue === undefined
    ? `var(${name})`
    : `color-mix(in srgb, var(${name}) calc(${opacityValue} * 100%), transparent)`;

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: tok("--bg"),
        fg: tok("--fg"),
        panel: tok("--panel"),
        border: tok("--border"),
        red: tok("--red"),
        green: tok("--green"),
        warn: tok("--warn"),
        
        // Legacy mappings
        paper: tok("--bg"),
        ink: tok("--fg"),
        muted: tok("--color-muted"),
        faint: tok("--color-muted-alt"),
        line: tok("--border"),
        lineStrong: tok("--border"),
        accent: tok("--color-accent"),
        accentSoft: tok("--accent-soft"),
        ok: tok("--color-success"),
        okSoft: tok("--ok-soft"),
        okLine: tok("--color-success"),
        warnInk: tok("--warn"),
        warnSoft: tok("--warn-soft"),
        danger: tok("--color-error"),
        dangerSoft: tok("--danger-soft"),
        tealInk: tok("--teal-ink"),
        tealSoft: tok("--teal-soft"),
        tealLine: tok("--teal-line"),
        solid: tok("--solid"),
        onSolid: tok("--on-solid"),
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Inter", "system-ui", "sans-serif"],
        mono: ["SF Mono", "JetBrains Mono", "Menlo", "monospace"],
      },
      borderRadius: { xl2: "14px" },
    },
  },
  plugins: [],
};
