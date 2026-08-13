import { fetch, httpBase } from "./client";

export interface ConnectorField {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  help: string;
  placeholder: string;
}

export interface ParkedMessage {
  id: string;
  platform: string;
  chat_id: string;
  chat_name: string | null;
  user_id: string;
  user_name: string | null;
  chat_type: string;
  text: string;
  ts: number;
  team_id?: string | null;
}

export interface SlackWorkspace {
  team_id: string;
  account: string;
  domain?: string;
  allowed_users: string[];
  allow_all: boolean;
  allowed_user_names?: Record<string, string | null>;
  approval_owner_ids?: string[];
  approval_owner_names?: Record<string, string | null>;
  installer_user_id?: string;
  installer_name?: string;
}

export interface GithubInstallation {
  installation_id: string;
  account_login: string;
  account_type: string;
  repo_selection: string;
  github_login: string;
  allowed_users: string[];
  allow_all: boolean;
}

export interface HubSpotPortal {
  hub_id: string;
  name: string;
  sandbox: boolean;
  default: boolean;
  managed: boolean;
  access: "read" | "write" | "";
}

export interface GmailAccount {
  email: string;
  default: boolean;
  managed: boolean;
  scopes: string;
  needs_reauth: boolean;
}

export interface GmailFilters {
  senders: string[];
  labels: string[];
}

export interface AccountRow {
  account_id: string;
  name: string;
  default: boolean;
  managed: boolean;
}

export interface ConnectorTool {
  name: string;
  label: string;
  kind: "read" | "write" | string;
  description: string;
  enabled: boolean;
  requires_approval: boolean;
}

export interface RecentSender {
  user_id: string;
  user_name: string | null;
  chat_id: string;
  chat_type: string;
  target: string;
  authorized: boolean;
  team_id?: string | null;
}

export interface Connector {
  name: string;
  title: string;
  icon: string;
  blurb: string;
  about?: string;
  access?: string[];
  auth: string;
  two_way: boolean;
  channels: boolean;
  available: boolean;
  fields: ConnectorField[];
  instructions: string[];
  connected: boolean;
  account: string | null;
  enabled: boolean;
  brand_color: string;
  logo: string;
  aliases?: string[];
  mcp?: boolean;
  allowed_users: string[];
  allowed_user_names?: Record<string, string | null>;
  approval_owner_ids?: string[];
  approval_owner_names?: Record<string, string | null>;
  recent?: RecentSender[];
  unauthorized?: ParkedMessage[];
  tools: ConnectorTool[];
  managed: boolean;
  managed_paused?: boolean;
  managed_profile: boolean;
  mode?: string;
  workspaces?: SlackWorkspace[];
  accounts?: GmailAccount[] | AccountRow[];
  filters?: GmailFilters;
  portals?: HubSpotPortal[];
  hidden_fields?: string[];
  installations?: GithubInstallation[];
}



export async function connectMcpBacked(name: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(
    `${httpBase()}/v1/connectors/${encodeURIComponent(name)}/mcp-connect`,
    { method: "POST" },
  );
  return res.json();
}

export async function getConnectors(): Promise<Connector[]> {
  const res = await fetch(`${httpBase()}/v1/connectors`);
  return (await res.json()).connectors ?? [];
}

export async function connectConnector(
  name: string,
  fields: Record<string, string>,
): Promise<{ ok: boolean; account?: string; error?: string }> {
  const res = await fetch(`${httpBase()}/v1/connectors/${encodeURIComponent(name)}/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields }),
  });
  return res.json();
}

export async function disconnectConnector(name: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${httpBase()}/v1/connectors/${encodeURIComponent(name)}/disconnect`, {
    method: "POST",
  });
  return res.json();
}

export async function updateConnectorTools(
  name: string,
  enabled: Record<string, boolean>,
): Promise<{ ok: boolean; error?: string; tools?: Record<string, boolean> }> {
  const res = await fetch(`${httpBase()}/v1/connectors/${encodeURIComponent(name)}/tools`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return res.json();
}
