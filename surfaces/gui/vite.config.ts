import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** Mirror `cogniwork.secrets.state_dir()` so dev reads the same token file as the server. */
function resolveStateDir(): string {
  const override = process.env.COGNIWORK_STATE_DIR || process.env.COWORKER_STATE_DIR;
  if (override) return override;
  const configBase =
    process.platform === "win32"
      ? path.join(process.env.APPDATA || os.homedir())
      : path.join(os.homedir(), ".config");
  const newDir = path.join(configBase, "cogniwork");
  const legacyDir = path.join(configBase, "coworker");
  try {
    if (fs.existsSync(legacyDir) && !fs.existsSync(newDir)) return legacyDir;
  } catch {
    /* fall through */
  }
  return newDir;
}

function readSidecarToken(state: string, port = 8765): string {
  const configBase = path.dirname(state);
  const dirs = [state];
  const legacy = path.join(configBase, "coworker");
  const modern = path.join(configBase, "cogniwork");
  if (!dirs.includes(legacy)) dirs.push(legacy);
  if (!dirs.includes(modern)) dirs.push(modern);
  for (const dir of dirs) {
    try {
      return fs.readFileSync(path.join(dir, `sidecar-${port}.token`), "utf8").trim();
    } catch {
      /* try next */
    }
  }
  return "";
}

// `base: "./"` makes built asset URLs relative, so the bundle loads from the `tauri://`
// origin in the desktop shell (absolute `/assets` 404s there); a server-hosted build is
// unaffected. Dev runs on a fixed port (1420) with strictPort so the Tauri webview always
// loads the vite instance Tauri itself spawns (a drifting port would make the window load a
// stale/other server). `tauri.conf.json` devUrl must match this.
export default defineConfig(({ command }) => {
  let devToken = "";
  if (command === "serve") {
    devToken = readSidecarToken(resolveStateDir());
  }
  return {
    base: "./",
    plugins: [react()],
    server: {
      port: 1420,
      strictPort: true,
      proxy: {
        "/v1": { target: "http://127.0.0.1:8765", changeOrigin: true },
        "/ws": { target: "ws://127.0.0.1:8765", ws: true, changeOrigin: true },
      },
    },
    define: { __COGNIWORK_DEV_TOKEN__: JSON.stringify(devToken) },
    // Tauri CLI looks for these; harmless for the browser build.
    clearScreen: false,
    envPrefix: ["VITE_", "TAURI_"],
  };
});
