import { useEffect, useRef, useState, type ReactNode } from "react";
// Emits the asset URL only; the worker itself loads lazily with the pdfjs chunk.
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {
  getArtifacts,
  readArtifact,
  revealArtifact,
  type ArtifactContent,
  type ArtifactInfo,
} from "../api";
import { humanizeTool } from "../humanize";
import type { TodoItem, ToolItem } from "../types";
import { AccessSection } from "./AccessSection";
import { Icon } from "./Icon";
import { Markdown, OPEN_ARTIFACT_EVENT } from "./Markdown";

type RailTab = "progress" | "artifacts" | "access";

// Quiet file-type icons for the artifact list (the colored kind pills read as noisy).
function kindIcon(kind: string): "file" | "fileCode" | "image" | "table" {
  if (kind === "image") return "image";
  if (kind === "html" || kind === "code") return "fileCode";
  if (kind === "csv" || kind === "sheet") return "table";
  return "file"; // markdown, text, pdf, everything else
}

// Fallback kind for an artifact: link whose path isn't in the list (yet) — mirrors the
// server's extension mapping closely enough for the viewer to pick a renderer.
function kindFromPath(path: string): string {
  const ext = (path.split(".").pop() || "").toLowerCase();
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext)) return "image";
  if (["html", "htm"].includes(ext)) return "html";
  if (ext === "md") return "markdown";
  if (ext === "csv") return "csv";
  if (ext === "pdf") return "pdf";
  if (["py", "js", "ts", "tsx", "jsx", "json", "sh", "css"].includes(ext)) return "code";
  return "text";
}

interface Props {
  active: boolean;
  sessionId: string;
  refreshKey: number;
  tools?: ToolItem[];
  toolNames?: string[];
  todo: TodoItem[];
  running: boolean;
  // Fires when a full artifact preview opens/closes, so the app can auto-collapse the left nav
  // to give the preview (PDF/webpage/sheet) more room (#3).
  onPreviewChange?: (open: boolean) => void;
  // §32: the rail is the ONE session panel for every non-chat persona. Artifacts stays
  // cogniwork-only (deliverables; code-family gets "Files" later — slot reserved); the Access
  // section (the former Session-settings drawer) renders for all.
  showArtifacts?: boolean;
  personaId?: string;
  projectScoped?: boolean;
  workspace?: string;
  branch?: string | null;
  scratchPrimary?: boolean;
  openAccessKey?: number;
  onOpenIntegrations?: () => void;
}

export function RightRail({
  active,
  sessionId,
  refreshKey,
  tools = [],
  toolNames = [],
  todo,
  running,
  onPreviewChange,
  showArtifacts = true,
  personaId,
  projectScoped,
  workspace,
  branch,
  scratchPrimary,
  openAccessKey = 0,
  onOpenIntegrations,
}: Props) {
  const [activeTab, setActiveTab] = useState<RailTab>("progress");
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [selected, setSelected] = useState<ArtifactInfo | null>(null);
  const [content, setContent] = useState<ArtifactContent | null>(null);

  const refreshArtifacts = () => getArtifacts(sessionId).then(setArtifacts).catch(() => setArtifacts([]));

  useEffect(() => {
    if (!active) return;
    if (showArtifacts) refreshArtifacts();
  }, [active, sessionId, refreshKey, showArtifacts]);

  // Deep links into Access switch to the access tab
  const seenAccessKey = useRef(openAccessKey);
  useEffect(() => {
    if (openAccessKey && openAccessKey !== seenAccessKey.current) {
      seenAccessKey.current = openAccessKey;
      setActiveTab("access");
    }
  }, [openAccessKey]);

  useEffect(() => {
    if (!showArtifacts && activeTab === "artifacts") {
      setActiveTab("progress");
    }
  }, [showArtifacts, activeTab]);

  // Switching conversations closes any open artifact — it belongs to the previous session's
  // workspace, which the new session can't (and shouldn't) read.
  useEffect(() => {
    setSelected(null);
    setContent(null);
  }, [sessionId]);

  useEffect(() => {
    setContent(null);
    if (!selected) return;
    readArtifact(sessionId, selected.path).then(setContent).catch(() => setContent(null));
  }, [selected?.path, sessionId]);

  // Notify the app when a preview opens/closes (drives the left-nav auto-collapse).
  useEffect(() => {
    onPreviewChange?.(!!selected);
  }, [!!selected, onPreviewChange]);

  const reloadSelected = () => {
    if (!selected) return Promise.resolve();
    setContent(null);
    return readArtifact(sessionId, selected.path).then(setContent).catch(() => setContent(null));
  };

  // §34 (UX-016): [Title](artifact:path) chips in the transcript open the viewer directly.
  // Resolve against the loaded list first; on a miss, refresh once (the file may be
  // seconds old), then fall back to a minimal record — readArtifact validates the path.
  useEffect(() => {
    if (!active) return;
    const minimal = (path: string): ArtifactInfo => ({
      path,
      name: path.split("/").pop() || path,
      kind: kindFromPath(path),
      size: 0,
      modified_at: 0,
    });
    const match = (list: ArtifactInfo[], path: string) =>
      list.find((a) => a.path === path || a.path.endsWith("/" + path) || a.name === path);
    const onOpen = (e: Event) => {
      const path = String((e as CustomEvent).detail?.path || "");
      if (!path) return;
      const found = match(artifacts, path);
      if (found) {
        setSelected(found);
        return;
      }
      getArtifacts(sessionId)
        .then((list) => {
          setArtifacts(list);
          setSelected(match(list, path) ?? minimal(path));
        })
        .catch(() => setSelected(minimal(path)));
    };
    window.addEventListener(OPEN_ARTIFACT_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_ARTIFACT_EVENT, onOpen);
  }, [active, sessionId, artifacts]);

  if (!active) return null;

  return (
    <aside className={"right-rail" + (selected ? " artifact-mode" : "")}>
      {selected ? (
        <ArtifactViewer
          sessionId={sessionId}
          artifact={selected}
          content={content}
          onReload={reloadSelected}
          onBack={() => {
            setSelected(null);
            setActiveTab("artifacts");
          }}
          onOpenEntry={(path) =>
            setSelected({
              path,
              name: path.split("/").pop() || path,
              kind: kindFromPath(path),
              size: 0,
              modified_at: 0,
            })
          }
        />
      ) : (
        <>
          {/* Permanent Top Icon Navigation Bar */}
          <div className="rail-nav-tabs" role="tablist" aria-label="Session panel tabs">
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "progress"}
              className={"rail-nav-tab" + (activeTab === "progress" ? " active" : "")}
              onClick={() => setActiveTab("progress")}
              title="Progress & Activity"
              data-testid="rail-tab-progress"
            >
              <Icon name="clock" size={14} />
              <span className="rail-tab-label">Progress</span>
              {running && <span className="rail-tab-dot-running" title="Running" />}
            </button>

            {showArtifacts && (
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "artifacts"}
                className={"rail-nav-tab" + (activeTab === "artifacts" ? " active" : "")}
                onClick={() => setActiveTab("artifacts")}
                title="Artifacts & Files"
                data-testid="rail-tab-artifacts"
              >
                <Icon name="file" size={14} />
                <span className="rail-tab-label">Artifacts</span>
                {artifacts.length > 0 && (
                  <span className="rail-tab-badge">{artifacts.length}</span>
                )}
              </button>
            )}

            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "access"}
              className={"rail-nav-tab" + (activeTab === "access" ? " active" : "")}
              onClick={() => setActiveTab("access")}
              title="Access & Permissions"
              data-testid="rail-tab-access"
            >
              <Icon name="shield" size={14} />
              <span className="rail-tab-label">Access</span>
            </button>
          </div>

          <div className="rail-tab-content">
            {/* Progress Pane */}
            <div
              className={"rail-tab-pane" + (activeTab === "progress" ? " active" : " hidden")}
              role="tabpanel"
              aria-label="Progress"
            >
              <div className="rail-pane-header">
                <span className="rail-pane-title">Progress</span>
                {running && <span className="rail-pill-running">Running</span>}
              </div>
              <div className="rail-pane-body">
                <ProgressSummary running={running} tools={tools} toolNames={toolNames} todo={todo} />
              </div>
            </div>

            {/* Artifacts Pane */}
            {showArtifacts && (
              <div
                className={"rail-tab-pane" + (activeTab === "artifacts" ? " active" : " hidden")}
                role="tabpanel"
                aria-label="Artifacts"
              >
                <div className="rail-pane-header">
                  <span className="rail-pane-title">
                    Artifacts{artifacts.length ? ` (${artifacts.length})` : ""}
                  </span>
                  <div className="rail-pane-actions">
                    {artifacts.length > 0 && (
                      <button
                        className="rail-mini-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          revealArtifact(sessionId, artifacts[0].path, "reveal");
                        }}
                        title="Show the folder where these files are saved"
                      >
                        <Icon name="folder" size={13} />
                      </button>
                    )}
                    <button
                      className="rail-mini-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        refreshArtifacts();
                      }}
                      title="Refresh artifacts"
                    >
                      <Icon name="refresh" size={13} />
                    </button>
                  </div>
                </div>
                <div className="rail-pane-body">
                  {artifacts.length === 0 ? (
                    <div className="rail-muted">No previewable files yet.</div>
                  ) : (
                    <div className="artifact-list">
                      {artifacts.slice(0, 16).map((a) => (
                        <button className="artifact-row" key={a.path} onClick={() => setSelected(a)}>
                          <span className="artifact-ico" title={a.kind}>
                            <Icon name={kindIcon(a.kind)} size={17} />
                          </span>
                          <span className="artifact-name">
                            {a.name}
                            <span className="artifact-row-meta">{formatBytes(a.size)} · {formatTime(a.modified_at)}</span>
                          </span>
                          <span className="artifact-open">Open</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Access Pane */}
            <div
              className={"rail-tab-pane" + (activeTab === "access" ? " active" : " hidden")}
              role="tabpanel"
              aria-label="Access"
            >
              <AccessSection
                key={sessionId}
                personaId={personaId}
                sessionId={sessionId}
                projectScoped={projectScoped}
                workspace={workspace}
                branch={branch}
                scratchPrimary={scratchPrimary}
                openKey={openAccessKey}
                onOpenIntegrations={onOpenIntegrations}
              />
            </div>
          </div>
        </>
      )}
    </aside>
  );
}

function toolIconName(name: string): "file" | "fileCode" | "search" | "code" | "wrench" | "chat" | "book" {
  if (name.includes("file") || name === "replace_in_file" || name === "apply_patch") return "fileCode";
  if (name.includes("search") || name === "grep") return "search";
  if (name.includes("shell") || name.includes("bash") || name.includes("terminal")) return "code";
  if (name.includes("message") || name.includes("slack")) return "chat";
  if (name.includes("skill")) return "book";
  return "wrench";
}

function ProgressSummary({
  running,
  tools = [],
  toolNames = [],
  todo = [],
}: {
  running: boolean;
  tools?: ToolItem[];
  toolNames?: string[];
  todo?: TodoItem[];
}) {
  // If tools array was not passed, fallback to toolNames
  const resolvedTools: ToolItem[] =
    tools.length > 0
      ? tools
      : toolNames.map((name, idx) => ({
          kind: "tool" as const,
          id: `tool-${idx}`,
          name,
          args: {},
          status: "done",
        }));

  const hasTodo = todo.length > 0;
  const hasTools = resolvedTools.length > 0;

  if (!hasTodo && !hasTools) {
    if (running) {
      return (
        <div className="rail-running-state">
          <div className="rail-todo in_progress">
            <span className="rail-todo-mark" />
            <span className="text-[12.5px] font-medium text-ink">Working on task…</span>
          </div>
          <div className="rail-muted mt-2">Preparing plan and calling tools…</div>
        </div>
      );
    }
    return (
      <div className="rail-muted">
        For longer multi-step tasks, progress, plan items, and tool executions will appear here in real-time.
      </div>
    );
  }

  return (
    <div className="rail-progress-content">
      {hasTodo && (
        <div className="rail-todo-section">
          <div className="rail-subhead">Plan Checklist</div>
          <div className="rail-todo-list">
            {todo.map((item, index) => (
              <div className={"rail-todo " + item.status} key={index}>
                <span className="rail-todo-mark" />
                <span className="rail-todo-text">{item.content}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasTools && (
        <div className={"rail-tools-section" + (hasTodo ? " mt-3 pt-3 border-t border-line" : "")}>
          <div className="rail-subhead flex items-center justify-between">
            <span>Tools Used ({resolvedTools.length})</span>
            {running && <span className="rail-pill-running text-[9.5px]">Running</span>}
          </div>
          <div className="rail-tool-list">
            {resolvedTools.map((tool, index) => {
              const line = humanizeTool(tool.name, tool.args);
              const isRunning = tool.status === "…";
              const isError = tool.status === "error" || tool.status === "failed";
              return (
                <div
                  className={"rail-tool-item" + (isRunning ? " running" : isError ? " error" : " done")}
                  key={tool.id || index}
                >
                  <span className="rail-tool-ico" title={tool.name}>
                    <Icon name={toolIconName(tool.name)} size={13} />
                  </span>
                  <div className="rail-tool-details">
                    <div className="rail-tool-line">
                      <span className="rail-tool-pre">{line.pre}</span>
                      {line.obj && <strong className="rail-tool-obj">{line.obj}</strong>}
                      {line.post && <span className="rail-tool-post">{line.post}</span>}
                    </div>
                  </div>
                  {isRunning ? (
                    <span className="rail-tab-dot-running" title="Running" />
                  ) : (
                    <span className="rail-tool-status-tag">{tool.status || "done"}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function RailSection({
  title,
  open,
  onToggle,
  children,
  action,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="rail-section">
      <div className="rail-section-head">
        <button className="rail-section-toggle" onClick={onToggle}>
          <Icon name={open ? "chevronDown" : "chevronRight"} size={14} className="rail-chev" />
          <span>{title}</span>
        </button>
        {action}
      </div>
      {open && <div className="rail-section-body">{children}</div>}
    </section>
  );
}

function ArtifactViewer({
  sessionId,
  artifact,
  content,
  onReload,
  onBack,
  onOpenEntry,
}: {
  sessionId: string;
  artifact: ArtifactInfo;
  content: ArtifactContent | null;
  onReload: () => Promise<void>;
  onBack: () => void;
  // Folder listings: open a child entry in the viewer (files and subfolders alike).
  onOpenEntry?: (path: string) => void;
}) {
  const [reloadKey, setReloadKey] = useState(0);
  const isHtml = content?.kind === "html" && !content.error;
  // Best viewed in a real app: spreadsheets, PDFs, and Office docs (pptx/docx can't preview inline)
  const isApp = content?.kind === "sheet" || content?.kind === "pdf" || content?.kind === "office";

  return (
    <div className="artifact-viewer">
      <div className="artifact-head">
        <button className="artifact-icon-btn" onClick={onBack} aria-label="Back to artifacts" title="Back">
          <Icon name="arrowLeft" size={16} />
        </button>
        <div className="artifact-heading">
          <div className="artifact-title"><span>Artifacts</span><span className="artifact-sep">/</span><span>{artifact.name}</span></div>
          <div className="artifact-path">{artifact.path}</div>
        </div>
        <div className="rail-actions">
          {isHtml && (
            <button
              className="artifact-icon-btn"
              onClick={async () => {
                await onReload();
                setReloadKey((k) => k + 1);
              }}
              aria-label="Reload preview"
              title="Reload"
            >
              <Icon name="refresh" size={16} />
            </button>
          )}
          {isApp && (
            <button
              className="artifact-icon-btn"
              onClick={() => revealArtifact(sessionId, artifact.path, "open")}
              aria-label="Open in default app"
              title="Open in default app"
            >
              <Icon name="panelOpen" size={16} />
            </button>
          )}
          {/* Copy the ABSOLUTE path — the workspace-relative one is useless outside the app
              (tester catch 2026-07-12: it copied just "slack-connector-debug.md"). */}
          <button
            className="artifact-icon-btn"
            onClick={() => navigator.clipboard?.writeText(artifact.abs_path || artifact.path)}
            aria-label="Copy path"
            title="Copy full path"
          >
            <Icon name="copy" size={16} />
          </button>
          <button
            className="artifact-icon-btn"
            onClick={() => revealArtifact(sessionId, artifact.path, "reveal")}
            aria-label="Show in folder"
            title="Show in folder"
          >
            <Icon name="folder" size={16} />
          </button>
        </div>
      </div>
      <div className="artifact-preview">
        {!content ? (
          <div className="rail-muted">Loading...</div>
        ) : content.error ? (
          <div className="rail-error">{content.error}</div>
        ) : content.kind === "html" ? (
          <iframe
            key={`${artifact.path}-${reloadKey}`}
            sandbox="allow-scripts allow-same-origin"
            className="artifact-frame"
            srcDoc={content.content || ""}
          />
        ) : content.kind === "markdown" ? (
          <div className="artifact-md">
            <Markdown text={content.content || ""} />
          </div>
        ) : content.kind === "image" ? (
          <img className="artifact-image" src={content.data_url} />
        ) : content.kind === "pdf" ? (
          <PdfViewer dataUrl={content.data_url || ""} />
        ) : content.kind === "csv" ? (
          <CsvTable text={content.content || ""} />
        ) : content.kind === "sheet" ? (
          <SheetViewer dataUrl={content.data_url || ""} />
        ) : content.kind === "folder" ? (
          // A linked directory (e.g. a skill package): render the listing, click through.
          <div className="artifact-folderlist" data-testid="artifact-folder">
            {(content.entries || []).map((e) => (
              <button
                key={e.name}
                className="artifact-folder-row"
                onClick={() => onOpenEntry?.(`${artifact.path.replace(/\/+$/, "")}/${e.name}`)}
              >
                <Icon name={e.dir ? "folder" : "file"} size={14} />
                <span className="artifact-folder-name">{e.name}</span>
                {!e.dir && <span className="artifact-folder-size">{formatBytes(e.size)}</span>}
              </button>
            ))}
            {!content.entries?.length && <div className="rail-muted">This folder is empty.</div>}
          </div>
        ) : content.kind === "office" ? (
          <div className="artifact-open-prompt">
            <Icon name="panelOpen" size={28} />
            <p>This {/\.pptx?$/i.test(artifact.name) ? "PowerPoint" : "Word"} file can’t be previewed here.</p>
            <button className="btn sm" onClick={() => revealArtifact(sessionId, artifact.path, "open")}>
              Open in default app
            </button>
          </div>
        ) : (
          <pre className="artifact-code">{content.content}</pre>
        )}
      </div>
    </div>
  );
}

const MAX_TABLE_ROWS = 500;

function GridTable({ rows, note }: { rows: unknown[][]; note?: string }) {
  const [head, ...body] = rows;
  return (
    <div className="artifact-tablewrap">
      <table className="artifact-table">
        {head && (
          <thead>
            <tr>{head.map((c, i) => <th key={i}>{String(c ?? "")}</th>)}</tr>
          </thead>
        )}
        <tbody>
          {body.slice(0, MAX_TABLE_ROWS).map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{String(c ?? "")}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {(note || body.length > MAX_TABLE_ROWS) && (
        <div className="rail-muted artifact-table-note">
          {note}
          {body.length > MAX_TABLE_ROWS ? ` Showing first ${MAX_TABLE_ROWS} of ${body.length} rows.` : ""}
        </div>
      )}
    </div>
  );
}

// Minimal RFC-4180-ish CSV parsing: quoted fields, escaped quotes, CRLF. TSV via tab sniffing.
function parseCsv(text: string): string[][] {
  const delim = text.includes("\t") && !text.split("\n")[0]?.includes(",") ? "\t" : ",";
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === delim) {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      cell = "";
      rows.push(row);
      row = [];
    } else cell += ch;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c !== ""));
}

function CsvTable({ text }: { text: string }) {
  const rows = parseCsv(text);
  if (!rows.length) return <div className="rail-muted artifact-table-note">Empty file.</div>;
  return <GridTable rows={rows} />;
}

// xlsx/xls preview via SheetJS (loaded on demand — it's a heavy module): sheet tabs + a capped
// grid. Real spreadsheet work belongs in Numbers/Excel via "Open in default app".
// WKWebView has no inline PDF plugin (<embed> shows a gray pane in the Tauri shell), so we
// rasterize pages with pdf.js onto stacked canvases — same lazy-chunk pattern as SheetViewer.
function PdfViewer({ dataUrl }: { dataUrl: string }) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const holder = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError("");
    setLoading(true);
    const base64 = dataUrl.split(",")[1] || "";
    import("pdfjs-dist")
      .then(async (pdfjs) => {
        pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
        const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
        const doc = await pdfjs.getDocument({ data: bytes }).promise;
        const el = holder.current;
        if (cancelled || !el) return;
        el.innerHTML = "";
        const width = el.clientWidth || 640;
        const dpr = window.devicePixelRatio || 1;
        for (let i = 1; i <= doc.numPages; i++) {
          const page = await doc.getPage(i);
          const base = page.getViewport({ scale: 1 });
          const viewport = page.getViewport({ scale: (width / base.width) * dpr });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.className = "artifact-pdf-page";
          await page.render({ canvasContext: canvas.getContext("2d")!, viewport }).promise;
          if (cancelled) return;
          el.appendChild(canvas);
        }
        setLoading(false);
      })
      .catch((e) => !cancelled && setError(String(e?.message || e)));
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) return <div className="rail-error artifact-table-note">Could not render PDF: {error}</div>;
  return (
    <div className="artifact-pdfjs">
      {loading && <div className="rail-muted artifact-table-note">Rendering PDF…</div>}
      <div ref={holder} />
    </div>
  );
}

function SheetViewer({ dataUrl }: { dataUrl: string }) {
  const [sheets, setSheets] = useState<{ name: string; rows: unknown[][] }[] | null>(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setSheets(null);
    setError("");
    setActive(0);
    const base64 = dataUrl.split(",")[1] || "";
    import("xlsx")
      .then((XLSX) => {
        if (cancelled) return;
        const wb = XLSX.read(base64, { type: "base64" });
        setSheets(
          wb.SheetNames.map((name) => ({
            name,
            rows: XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, defval: "" }) as unknown[][],
          })),
        );
      })
      .catch((e) => !cancelled && setError(String(e?.message || e)));
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) return <div className="rail-error artifact-table-note">Could not parse spreadsheet: {error}</div>;
  if (!sheets) return <div className="rail-muted artifact-table-note">Parsing spreadsheet…</div>;
  const sheet = sheets[active];
  return (
    <div className="sheet-viewer">
      {sheets.length > 1 && (
        <div className="sheet-tabs">
          {sheets.map((s, i) => (
            <button key={s.name} className={"sheet-tab" + (i === active ? " active" : "")} onClick={() => setActive(i)}>
              {s.name}
            </button>
          ))}
        </div>
      )}
      {sheet.rows.length ? <GridTable rows={sheet.rows} /> : <div className="rail-muted artifact-table-note">Empty sheet.</div>}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(epochSeconds: number): string {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
