import { readFileSync, readdirSync, statSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import type { Page } from "@playwright/test";

// Shared helpers for the LIVE smoke specs (real backend + real model). Kept out of the hermetic
// suite (separate dir/config); see e2e/README.md.

export const BACKEND = "http://127.0.0.1:8765";

function resolveStateDir(): string {
  const override = process.env.COGNIWORK_STATE_DIR || process.env.COWORKER_STATE_DIR;
  if (override) return override;
  const configBase =
    process.platform === "win32"
      ? join(process.env.APPDATA || homedir())
      : join(homedir(), ".config");
  const newDir = join(configBase, "cogniwork");
  const legacyDir = join(configBase, "coworker");
  try {
    const { existsSync } = require("fs") as typeof import("fs");
    if (existsSync(legacyDir) && !existsSync(newDir)) return legacyDir;
  } catch {
    /* fall through */
  }
  return newDir;
}

function sidecarToken(): string {
  const state = resolveStateDir();
  const configBase = join(state, "..");
  for (const dir of [state, join(configBase, "coworker"), join(configBase, "cogniwork")]) {
    try {
      return readFileSync(join(dir, "sidecar-8765.token"), "utf8").trim();
    } catch {
      /* try next */
    }
  }
  return "";
}

/** Fetch from the live sidecar with its per-launch authentication token. */
export function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = sidecarToken();
  if (token) headers.set("X-CogniOS-Token", token);
  return fetch(`${BACKEND}${path}`, { ...init, headers });
}

/** The expanded scratch base if the backend is up and a model is ready — else null (→ skip). */
export async function scratchBaseIfReady(): Promise<string | null> {
  try {
    const res = await backendFetch("/v1/settings");
    const s = await res.json();
    if (res.ok && s.model_ready) {
      return String(s.scratch_base || "~/CogniOS").replace(/^~(?=\/|$)/, homedir());
    }
  } catch {
    /* backend unreachable */
  }
  return null;
}

/** Newest `name` file across the per-session scratch dirs (each live session gets its own). */
export function newestFile(scratchBase: string, name: string): string | null {
  let best: { path: string; mtime: number } | null = null;
  let dirs: string[];
  try {
    dirs = readdirSync(scratchBase);
  } catch {
    return null;
  }
  for (const d of dirs) {
    const f = join(scratchBase, d, name);
    try {
      const st = statSync(f);
      if (!best || st.mtimeMs > best.mtime) best = { path: f, mtime: st.mtimeMs };
    } catch {
      /* not in this session dir */
    }
  }
  return best?.path ?? null;
}

/** Open a fresh CogniWork session via the split button's persona menu. */
export async function startCogniworkSession(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Choose a persona" }).click();
  await page.getByText(/Produce a deliverable/).click();
}
export const startCoworkSession = startCogniworkSession;

/** Switch the composer's permission mode from the default "Ask for approval". */
export async function selectMode(page: Page, label: "Full access" | "Plan" | "Discuss") {
  await page.getByText("Ask for approval").click();
  await page.getByText(label, { exact: true }).click();
}

/** Type a task and send it. */
export async function sendTask(page: Page, text: string) {
  await page.getByPlaceholder(/Ask CogniWork/).fill(text);
  // exact — "Send" is a substring of the Inbox control's "Sending approvals…" title when unattended.
  await page.getByRole("button", { name: "Send", exact: true }).click();
}
