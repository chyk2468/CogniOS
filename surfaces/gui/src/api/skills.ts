import { fetch, httpBase } from "./client";

export interface SkillRow {
  name: string;
  description: string;
  instructions: string;
  scope: "global" | "project";
  source: string;
  enabled: boolean;
  path: string;
  files?: number;
}

export interface SessionSkillRow {
  name: string;
  description: string;
  scope: "global" | "project";
  enabled: boolean;
}

export interface SkillUploadPreview {
  ok: boolean;
  error?: string;
  token?: string;
  name?: string;
  description?: string;
  instructions?: string;
  files?: string[];
}

const skillUrl = (path = "") => `${httpBase()}/v1/skills${path}`;
const jsonPost = (body: unknown, method = "POST") => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export async function listSkills(workspace?: string): Promise<SkillRow[]> {
  const qs = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
  const res = await fetch(skillUrl(qs));
  return (await res.json()).skills ?? [];
}

export async function createSkill(body: {
  name: string;
  description: string;
  instructions: string;
  scope?: "global" | "project";
  workspace?: string;
}): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(skillUrl(), jsonPost(body));
  return res.json();
}

export async function updateSkill(
  name: string,
  patch: { description?: string; instructions?: string; enabled?: boolean; workspace?: string },
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(skillUrl(`/${encodeURIComponent(name)}`), jsonPost(patch, "PATCH"));
  return res.json();
}

export async function revealSkill(name: string): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(skillUrl(`/${encodeURIComponent(name)}/reveal`), jsonPost({}));
  return res.json();
}

export async function deleteSkill(
  name: string,
  workspace?: string,
): Promise<{ ok: boolean; error?: string }> {
  const qs = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
  const res = await fetch(skillUrl(`/${encodeURIComponent(name)}${qs}`), { method: "DELETE" });
  return res.json();
}

export async function moveSkill(
  name: string,
  scope: "global" | "project",
  workspace?: string,
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(skillUrl(`/${encodeURIComponent(name)}/move`), jsonPost({ scope, workspace }));
  return res.json();
}

export async function stageSkillUpload(
  dataB64: string,
  filename = "",
): Promise<SkillUploadPreview> {
  const res = await fetch(skillUrl("/upload"), jsonPost({ data_b64: dataB64, filename }));
  return res.json();
}

export async function confirmSkillUpload(
  token: string,
  scope: "global" | "project" = "global",
  workspace?: string,
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(skillUrl("/upload/confirm"), jsonPost({ token, scope, workspace }));
  return res.json();
}

export async function sessionSkills(
  sessionId: string,
  workspace?: string,
): Promise<SessionSkillRow[]> {
  const qs = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
  const res = await fetch(
    `${httpBase()}/v1/sessions/${encodeURIComponent(sessionId)}/skills${qs}`,
  );
  return (await res.json()).skills ?? [];
}

export async function setSessionSkill(
  sessionId: string,
  skill: string,
  enabled: boolean,
  opts: { clear?: boolean; workspace?: string } = {},
): Promise<{ skills?: SessionSkillRow[]; ok?: boolean; error?: string }> {
  const res = await fetch(
    `${httpBase()}/v1/sessions/${encodeURIComponent(sessionId)}/skills`,
    jsonPost({
      skill,
      enabled,
      ...(opts.clear ? { clear: true } : {}),
      ...(opts.workspace ? { workspace: opts.workspace } : {}),
    }),
  );
  return res.json();
}
