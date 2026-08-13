import { fetch, httpBase } from "./client";

export const PERSONAS_CHANGED = "coworker:personas-changed";
function announcePersonasChanged() {
  window.dispatchEvent(new CustomEvent(PERSONAS_CHANGED));
}

export interface Persona {
  id: string;
  name: string;
  icon: string;
  tagline: string;
  needs_workspace: boolean;
  builtin: boolean;
  family: string;
  workspace: string;
  tools: string[];
  enabled: boolean;
  surfaced: boolean;
  default: boolean;
}

export interface PersonaConsent {
  id: string;
  name: string;
  description: string;
  tools: string[];
  risk: string[];
  connectors: boolean;
  mcp: string[];
  messaging: boolean;
  recommended_mode: string;
  recommended_models: string[];
  source: string | null;
  builtin: boolean;
}

export async function getPersonas(): Promise<Persona[]> {
  const res = await fetch(`${httpBase()}/v1/personas`);
  return (await res.json()).personas;
}

export async function updatePersona(
  id: string,
  body: { enabled?: boolean; surfaced?: boolean; default?: boolean },
): Promise<{ ok: boolean; personas?: Persona[]; error?: string }> {
  const res = await fetch(`${httpBase()}/v1/personas/${encodeURIComponent(id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const out = await res.json();
  if (out.ok !== false) announcePersonasChanged();
  return out;
}

export async function deletePersona(
  id: string,
): Promise<{ ok: boolean; personas?: Persona[]; error?: string }> {
  const res = await fetch(`${httpBase()}/v1/personas/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  const out = await res.json();
  if (out.ok) announcePersonasChanged();
  return out;
}



export async function installPersona(
  body: { dir?: string; git_url?: string },
): Promise<{ ok: boolean; consent?: PersonaConsent[]; personas?: Persona[]; error?: string }> {
  const res = await fetch(`${httpBase()}/v1/personas/install`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const out = await res.json();
  if (out.ok) announcePersonasChanged();
  return out;
}

export interface PersonaRecommendation {
  kind: string;
  ref: string;
  reason: string;
  tier: string;
  connected: boolean;
}

export interface PersonaDefaultConnection {
  connector: string;
  enabled: boolean;
  connected: boolean;
}

export interface PersonaDetail {
  id: string;
  name: string;
  icon: string;
  tagline: string;
  description: string;
  enabled: boolean;
  tools: string[];
  recommended_models: string[];
  default_permission_mode: string;
  workspace: string;
  recommends: PersonaRecommendation[];
  default_connections: PersonaDefaultConnection[];
}

export async function getPersonaDetail(id: string): Promise<PersonaDetail> {
  const res = await fetch(`${httpBase()}/v1/personas/${encodeURIComponent(id)}`);
  return res.json();
}

export async function setPersonaConnection(
  id: string,
  connector: string,
  enabled: boolean,
): Promise<{ ok: boolean; default_connections?: PersonaDefaultConnection[]; error?: string }> {
  const res = await fetch(`${httpBase()}/v1/personas/${encodeURIComponent(id)}/connections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connector, enabled }),
  });
  return res.json();
}

export async function setPersonaEnabled(
  id: string,
  enabled: boolean,
): Promise<{ ok: boolean; personas?: Persona[]; error?: string }> {
  const res = await fetch(`${httpBase()}/v1/personas/${encodeURIComponent(id)}/enable`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  const out = await res.json();
  if (out.ok) announcePersonasChanged();
  return out;
}

export interface SessionConnectedConnector {
  connector: string;
  enabled: boolean;
  detail: string;
}

export interface SessionRecommendedConnector {
  connector: string;
  reason: string;
  tier: string;
  connected: boolean;
}

export interface SessionConnections {
  connected: SessionConnectedConnector[];
  recommended: SessionRecommendedConnector[];
  attention: number;
}

export async function getSessionConnections(
  sessionId: string,
  persona?: string,
): Promise<SessionConnections> {
  const q = persona ? `?persona=${encodeURIComponent(persona)}` : "";
  const res = await fetch(
    `${httpBase()}/v1/sessions/${encodeURIComponent(sessionId)}/connections${q}`,
  );
  return res.json();
}

export async function setSessionConnection(
  sessionId: string,
  connector: string,
  enabled: boolean,
  clear = false,
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${httpBase()}/v1/sessions/${encodeURIComponent(sessionId)}/connections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connector, enabled, ...(clear ? { clear: true } : {}) }),
  });
  return res.json();
}
