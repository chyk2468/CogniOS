declare const __COGNIWORK_DEV_TOKEN__: string;

import { isTauri } from "../tauri";

// Endpoint resolution order: runtime-injected globals (Tauri sets `window.__COGNIWORK_HTTP__`
// for its dynamically-chosen sidecar port) → Vite env → the 127.0.0.1:8765 dev default.
// In browser dev, use same-origin URLs so the Vite proxy can forward cookies for auth.
export const httpBase = (): string => {
  if (isTauri()) {
    return (
      (globalThis as any).__COGNIWORK_HTTP__ ||
      (import.meta as any).env?.VITE_COGNIWORK_HTTP ||
      "http://127.0.0.1:8765"
    );
  }
  return "";
};

export const wsBase = (): string => {
  if (isTauri()) {
    return (
      (globalThis as any).__COGNIWORK_WS__ ||
      (import.meta as any).env?.VITE_COGNIWORK_WS ||
      "ws://127.0.0.1:8765"
    );
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
};

export const apiToken = (): string =>
  (globalThis as any).__COGNIWORK_API_TOKEN__ ||
  (import.meta as any).env?.VITE_COGNIWORK_API_TOKEN ||
  (typeof __COGNIWORK_DEV_TOKEN__ === "string" ? __COGNIWORK_DEV_TOKEN__ : "");

// All local REST calls pass through this module wrapper applying launch authentication
export const fetch = (
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> => {
  const headers = new Headers(init.headers);
  const token = apiToken();
  if (token) headers.set("X-CogniOS-Token", token);
  return globalThis.fetch(input, { ...init, headers, credentials: "include" });
};

export const openWebSocket = (url: string): WebSocket => {
  const token = apiToken();
  return token
    ? new WebSocket(url, ["cognios", token])
    : new WebSocket(url);
};
