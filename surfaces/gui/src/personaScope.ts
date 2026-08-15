// A persona is "project-scoped" only when it's code-family: an explicit directory the user
// picks, sessions grouped by project in the sidebar. Everything else (knowledge, chat) runs on
// a transparent per-conversation scratch dir, with real folders added as roots when needed —
// no folder gate, ever. (The old workspace enum — git/project/deliverable/none — collapsed
// into family; owner decision 2026-07-03, UX-DECISIONS §16.)
export function isProjectScoped(p?: { workspace?: string; family?: string }): boolean {
  return p?.family === "code";
}

// Persona naming: the product is "CogniOS"; the personas are a "CogniWork" family — CogniWork
// (general), Code, Ops CogniWork. In lists/chrome we use the SHORT label (CogniWork / Code /
// Ops); the persona detail page uses the FULL family name.

// Short label for the sidebar + top bar: "CogniWork" / "Code" / "Ops" / "Chat".
export function shortPersonaName(name?: string, id?: string): string {
  if (id === "cogniwork" || id === "cowork") return "CogniWork";
  const n = (name || id || "").trim();
  return n.replace(/\s*cogniwork$/i, "").replace(/\s*coworker$/i, "").trim() || n;
}

// Full family name for the persona detail page: "CogniWork" / "Code CogniWork" / "Ops CogniWork".
export function fullPersonaName(name?: string, id?: string): string {
  if (id === "cogniwork" || id === "cowork") return "CogniWork";
  const n = (name || id || "").trim();
  if (id === "chat" || !n) return n;
  if (/cogniwork$/i.test(n) || /coworker$/i.test(n)) {
    return n.replace(/\s*coworker$/i, " CogniWork").replace(/\s*cogniwork$/i, " CogniWork").trim();
  }
  return `${n} CogniWork`;
}
