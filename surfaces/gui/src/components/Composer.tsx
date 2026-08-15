import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { Attachment, SessionUsage } from "../types";
import { isPdfFile, readFile } from "../attach";
import { getSettings, inspectPdf, sessionSkills, type SessionSkillRow } from "../api";
import { totalTokens } from "../usage";
import { Dropdown, type Option } from "./Dropdown";
import { Icon } from "./Icon";
import { isTauri } from "../tauri";
import { useVoiceInput } from "../hooks/useVoiceInput";
import { VoiceButton } from "./voice/VoiceButton";
import { UsageChip } from "./composer/UsageChip";
import { ModeMenu } from "./composer/ModeMenu";
import { AttachChip } from "./composer/AttachChip";

const shortModel = (m: string) => (m.includes(":") ? m.split(":").slice(1).join(":") : m);

const attKey = (a: Attachment) =>
  a.kind === "text"
    ? `t:${a.name}:${a.text?.length ?? 0}`
    : `${a.kind[0]}:${a.name}:${a.data_url?.length ?? 0}`;

const mergeAttachments = (cur: Attachment[], add: Attachment[]): Attachment[] => {
  const seen = new Set(cur.map(attKey));
  return [...cur, ...add.filter((a) => !seen.has(attKey(a)))].slice(0, 8);
};

const formatTimer = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

interface Props {
  mode: string;
  model: string;
  models?: string[];
  modelLabels?: Record<string, string>;
  running: boolean;
  connected: boolean;
  modelReady?: boolean;
  onConnectModel?: () => void;
  onConfigureVoiceInput?: () => void;
  onSend: (text: string, attachments?: Attachment[], skill?: string) => void;
  sessionId?: string;
  onInterrupt: () => void;
  onModeChange: (mode: string) => void;
  onModelChange: (model: string) => void;
  workspace?: string;
  unattended?: boolean;
  onUnattendedChange?: (on: boolean) => void;
  approvalSlot?: ReactNode;
  prefill?: { text: string; attachments?: Attachment[]; nonce: number };
  resetKey?: string;
  placeholder?: string;
  usage?: SessionUsage;
  contextWindow?: number;
  contextBar?: boolean;
}

export function Composer(props: Props) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [pendingSkill, setPendingSkill] = useState<SessionSkillRow | null>(null);
  const [slashSkills, setSlashSkills] = useState<SessionSkillRow[] | null>(null);
  const [slashIndex, setSlashIndex] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [attachNotice, setAttachNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const noticeTimer = useRef<number | null>(null);

  const baseTextRef = useRef("");

  const handleFinalTranscript = (finalTranscript: string) => {
    const base = baseTextRef.current;
    const prefix = base ? (base.endsWith(" ") || base.endsWith("\n") ? base : base + " ") : "";
    const updated = (prefix + finalTranscript).trim();
    setText(updated);
    setTimeout(() => {
      textareaRef.current?.focus();
    }, 10);
  };

  const voice = useVoiceInput({
    onFinalTranscript: handleFinalTranscript,
  });

  const handleStartVoice = () => {
    baseTextRef.current = text;
    void voice.startListening();
  };

  const handleStopVoice = () => {
    void voice.stopListening();
  };

  const handleVoiceToggle = () => {
    if (voice.isListening) {
      handleStopVoice();
    } else {
      handleStartVoice();
    }
  };

  const prefixIntact =
    pendingSkill !== null &&
    (text === `/${pendingSkill.name}` || text.startsWith(`/${pendingSkill.name} `));

  useEffect(() => {
    if (pendingSkill && !prefixIntact) setPendingSkill(null);
  }, [pendingSkill, prefixIntact]);

  const slashQuery =
    !prefixIntact && props.sessionId && text.startsWith("/") && !/\s/.test(text.slice(1))
      ? text.slice(1).toLowerCase()
      : null;

  const slashMatches = (slashSkills ?? []).filter((s) =>
    s.name.toLowerCase().includes(slashQuery ?? ""),
  );

  useEffect(() => {
    if (slashQuery === null) {
      setSlashSkills(null);
      setSlashIndex(0);
      return;
    }
    if (slashSkills === null && props.sessionId) {
      sessionSkills(props.sessionId, props.workspace)
        .then((all) => setSlashSkills(all.filter((s) => s.enabled)))
        .catch(() => setSlashSkills([]));
    }
  }, [props.sessionId, props.workspace, slashQuery, slashSkills]);

  const pickSkill = (s: SessionSkillRow) => {
    setPendingSkill(s);
    setText(`/${s.name} `);
    textareaRef.current?.focus();
  };

  const showAttachNotice = (message: string) => {
    setAttachNotice(message);
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setAttachNotice(null), 8000);
  };

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const max = parseFloat(getComputedStyle(el).lineHeight || "22") * 4;
    const next = Math.min(el.scrollHeight, max);
    el.style.height = `${Math.max(next, 24)}px`;
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  }, [text]);

  useEffect(() => {
    setText("");
    setAttachments([]);
    setPendingSkill(null);
  }, [props.resetKey]);

  const appliedNonce = useRef<number>(-1);
  useEffect(() => {
    const p = props.prefill;
    if (!p || p.nonce === appliedNonce.current) return;
    appliedNonce.current = p.nonce;
    setText(p.text);
    if (p.attachments?.length) setAttachments((cur) => mergeAttachments(cur, p.attachments!));
    textareaRef.current?.focus();
  }, [props.prefill]);

  // Escape key cancels voice recording and restores pre-recording draft text
  useEffect(() => {
    if (!voice.isActive) return;
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setText(baseTextRef.current);
        void voice.cancel();
      }
    };
    window.addEventListener("keydown", cancelOnEscape);
    return () => window.removeEventListener("keydown", cancelOnEscape);
  }, [voice]);

  const addFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    let maxPages = 20;
    let maxMb = 10;
    if (list.some(isPdfFile)) {
      try {
        const s = await getSettings();
        if (s.pdf_max_pages) maxPages = s.pdf_max_pages;
        if (s.pdf_max_mb) maxMb = s.pdf_max_mb;
      } catch {}
    }
    const accepted: File[] = [];
    for (const file of list) {
      if (isPdfFile(file) && file.size > maxMb * 1024 * 1024) {
        showAttachNotice(
          `${file.name} skipped - ${(file.size / 1024 / 1024).toFixed(1)} MB is over your ${maxMb} MB limit (Settings -> Token savings)`,
        );
        continue;
      }
      accepted.push(file);
    }
    const read = (await Promise.all(accepted.map(readFile))).filter(Boolean) as Attachment[];
    const next: Attachment[] = [];
    for (const a of read) {
      if (a.kind === "pdf" && a.data_url) {
        const info = await inspectPdf(a.data_url).catch(() => null);
        if (info?.ok && (info.pages ?? 0) > maxPages) {
          showAttachNotice(
            `${a.name} skipped - ${info.pages} pages is over your ${maxPages}-page limit (Settings -> Token savings)`,
          );
          continue;
        }
        if (info && !info.ok) {
          showAttachNotice(`${a.name} skipped - ${info.error || "could not read PDF"}`);
          continue;
        }
      }
      next.push(a);
    }
    if (next.length) setAttachments((a) => mergeAttachments(a, next));
  };

  const pickFiles = (accept: string) => {
    setAttachMenuOpen(false);
    if (fileInput.current) {
      fileInput.current.accept = accept;
      fileInput.current.click();
    }
  };

  const needsModel = props.modelReady === false;
  const voiceReady = isTauri()
    ? (!!voice.status?.supported && !!voice.status.model_verified && !!voice.status.test_passed)
    : true;

  const submit = () => {
    if (slashQuery !== null) return;
    const skill = prefixIntact ? pendingSkill!.name : undefined;
    const t = (skill ? text.slice(skill.length + 1) : text).trim();
    if ((!t && attachments.length === 0 && !skill) || props.running || voice.isActive) return;
    if (needsModel) {
      props.onConnectModel?.();
      return;
    }
    props.onSend(t, attachments, skill);
    setText("");
    setAttachments([]);
    setPendingSkill(null);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (voice.isActive) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
      }
      return;
    }
    if (slashQuery !== null) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashIndex((i) => Math.min(i + 1, Math.max(slashMatches.length - 1, 0)));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setText("");
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const chosen = slashMatches[slashIndex];
        if (chosen) pickSkill(chosen);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const onPaste = (e: React.ClipboardEvent) => {
    const imgs = Array.from(e.clipboardData.items)
      .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
      .map((it) => it.getAsFile())
      .filter(Boolean) as File[];
    if (imgs.length) {
      e.preventDefault();
      addFiles(imgs);
    }
  };

  const modelsLoaded = !!(props.models && props.models.length);
  const modelOptions: Option[] = Array.from(new Set([props.model, ...(props.models || [])])).map((m) => ({
    value: m,
    label: props.modelLabels?.[m] || shortModel(m),
  }));

  const iconBtn =
    "w-7 h-7 grid place-items-center rounded-md text-muted hover:text-fg hover:bg-bg shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60";

  const hasContent = text.trim().length > 0 || attachments.length > 0 || !!pendingSkill;

  const attachItem = (icon: "image" | "file" | "fileCode", label: string, onClick: () => void) => (
    <button
      type="button"
      className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[13px] text-left hover:bg-bg"
      onClick={onClick}
    >
      <Icon name={icon} size={15} className="shrink-0 text-muted" /> {label}
    </button>
  );

  // Array of 18 waveform bars
  const waveLevels = voice.levels.length >= 18
    ? voice.levels.slice(-18)
    : [...Array(Math.max(0, 18 - voice.levels.length)).fill(0.12), ...voice.levels];

  return (
    <div className="composer-wrap">
      {props.approvalSlot}

      {voice.error && (
        <div className="max-w-3xl mx-auto mb-2 px-1 text-[12px] text-red-600" role="alert">
          {voice.error}
        </div>
      )}

      {attachNotice && (
        <div
          data-testid="attach-notice"
          className="max-w-3xl mx-auto mb-1.5 flex items-center gap-2 rounded-md border border-warnInk/30 bg-warnSoft px-3 py-1.5 text-[12.5px] text-warnInk"
        >
          <span className="flex-1">{attachNotice}</span>
          <button
            type="button"
            className="shrink-0 opacity-60 hover:opacity-100"
            onClick={() => setAttachNotice(null)}
            title="Dismiss"
          >
            x
          </button>
        </div>
      )}

      {attachments.length > 0 && (
        <div className="max-w-3xl mx-auto mb-1.5 flex flex-wrap gap-2">
          {attachments.map((a, i) => (
            <AttachChip key={i} a={a} onRemove={() => setAttachments((all) => all.filter((_, j) => j !== i))} />
          ))}
        </div>
      )}

      <div
        className={
          "composer max-w-3xl mx-auto rounded-md border border-border bg-panel shadow-sm transition-all focus-within:border-accent focus-within:ring-1 focus-within:ring-accent/50 " +
          (dragging ? " dragging border-accent" : "") +
          (voice.isListening ? " composer--listening" : "") +
          (voice.isTranscribing ? " composer--transcribing" : "")
        }
        aria-busy={voice.isTranscribing}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
        }}
      >
        {slashQuery !== null && (
          <div className="px-2 pt-2" data-testid="skill-popup" role="listbox" aria-label="Skills">
            {slashSkills === null ? (
              <div className="px-2 py-1.5 text-[12px] text-faint">Loading skills...</div>
            ) : slashMatches.length === 0 ? (
              <div className="px-2 py-1.5 text-[12px] text-faint">No matching skills.</div>
            ) : (
              slashMatches.map((s, i) => (
                <button
                  type="button"
                  key={s.name}
                  role="option"
                  aria-selected={i === slashIndex}
                  className={
                    "w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-md " +
                    (i === slashIndex ? "bg-bg" : "hover:bg-bg")
                  }
                  onMouseEnter={() => setSlashIndex(i)}
                  onClick={() => pickSkill(s)}
                >
                  <span className="text-[13px] font-medium text-accent shrink-0">/{s.name}</span>
                  <span className="text-[12px] text-faint truncate flex-1">{s.description}</span>
                  <span className="text-[10.5px] px-1.5 py-0.5 rounded-md border border-border text-faint shrink-0">
                    {s.scope}
                  </span>
                </button>
              ))
            )}
          </div>
        )}

        {voice.isTranscribing ? (
          <div className="w-full px-3.5 pt-3.5 pb-1.5 min-h-[44px]">
            <span className="voice-provisional font-mono text-[14.5px]">{text || "Transcribing speech…"}</span>
          </div>
        ) : (
          <textarea
            ref={textareaRef}
            className="w-full block px-3.5 pt-3.5 pb-1.5 text-[14.5px] bg-transparent outline-none text-fg placeholder:text-muted/60 resize-none font-mono"
            placeholder={props.placeholder || (voice.isListening ? "Speak now…" : "Ask CogniWork...  (drop or paste files)")}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            onPaste={onPaste}
            rows={1}
          />
        )}

        {/* State 2: Listening Row */}
        {voice.isListening ? (
          <div className="px-2.5 pb-2.5 pt-1 flex items-center gap-2.5">
            <button
              type="button"
              className={iconBtn}
              title="Attach"
              aria-label="Attach"
              disabled
            >
              <Icon name="plus" size={17} />
            </button>

            <div className="voice-wave-line" aria-hidden="true">
              <div className="voice-wave">
                {waveLevels.map((lvl, idx) => (
                  <i
                    key={idx}
                    style={{
                      transform: `scaleY(${Math.max(0.18, Math.min(1.0, lvl * 2.2))})`,
                    }}
                  />
                ))}
              </div>
            </div>

            <span className="voice-timer font-mono" aria-label={`Recording elapsed time ${formatTimer(voice.seconds)}`}>
              {formatTimer(voice.seconds)}
            </span>

            <button
              type="button"
              className="voice-stop-btn"
              onClick={handleStopVoice}
              title="Stop recording"
              aria-label="Stop recording"
            />

            <button
              type="button"
              className="w-7 h-7 rounded-full grid place-items-center shrink-0 bg-bg border border-border text-faint opacity-60 cursor-default"
              disabled
              aria-label="Send"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          </div>
        ) : voice.isTranscribing ? (
          /* State 3: Transcribing Row */
          <div className="px-2.5 pb-2.5 pt-1 flex items-center gap-1.5">
            <button
              type="button"
              className={iconBtn}
              title="Attach"
              aria-label="Attach"
              disabled
            >
              <Icon name="plus" size={17} />
            </button>

            {props.workspace !== undefined ? (
              <ModeMenu
                mode={props.mode}
                onModeChange={props.onModeChange}
                unattended={props.unattended}
                onUnattendedChange={props.onUnattendedChange}
              />
            ) : null}

            <span className="ml-auto" />

            <span className="voice-busy-copy" role="status" aria-live="polite">
              Transcribing…
            </span>

            <VoiceButton
              ready={true}
              transcribing={true}
              disabled={true}
              onClick={() => {}}
            />

            <button
              type="button"
              className="w-7 h-7 rounded-full grid place-items-center shrink-0 bg-bg border border-border text-faint opacity-50 cursor-default"
              disabled
              aria-label="Send unavailable while transcribing"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          </div>
        ) : (
          /* State 1 & 4: Ready at rest / Draft inserted */
          <div className="px-2.5 pb-2.5 pt-1 flex items-center gap-1.5">
            <div className="relative">
              <button
                type="button"
                className={iconBtn + (attachMenuOpen ? " bg-bg text-fg" : "")}
                title="Attach"
                aria-label="Attach"
                onClick={() => setAttachMenuOpen((v) => !v)}
              >
                <Icon name="plus" size={17} />
              </button>
              {attachMenuOpen && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setAttachMenuOpen(false)} />
                  <div className="absolute z-40 bottom-full mb-1 left-0 min-w-[180px] rounded-md border border-border bg-panel shadow-2xl py-1.5">
                    {attachItem("image", "Photo or image", () => pickFiles("image/*"))}
                    {attachItem("file", "PDF", () => pickFiles("application/pdf,.pdf"))}
                    {attachItem(
                      "fileCode",
                      "Other files",
                      () => pickFiles("text/*,.md,.csv,.json,.yaml,.yml,.log,.py,.ts,.tsx,.js,.rs,.go,.toml"),
                    )}
                  </div>
                </>
              )}
            </div>
            <input
              ref={fileInput}
              type="file"
              multiple
              style={{ display: "none" }}
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = "";
              }}
            />

            {props.workspace !== undefined ? (
              <ModeMenu
                mode={props.mode}
                onModeChange={props.onModeChange}
                unattended={props.unattended}
                onUnattendedChange={props.onUnattendedChange}
              />
            ) : null}

            <span className="ml-auto" />

            {props.usage && totalTokens(props.usage) > 0 && (
              <UsageChip
                usage={props.usage}
                contextWindow={props.contextWindow}
                contextBar={props.contextBar}
                model={props.model}
                modelLabels={props.modelLabels}
              />
            )}

            {needsModel ? (
              <button
                type="button"
                className="pill model-warn chip text-[12px] text-danger px-2 py-0.5 rounded-md bg-danger/10 border border-danger/30"
                onClick={() => props.onConnectModel?.()}
                title="Connect a model"
                aria-label="No model connected - connect a model"
              >
                <span className="pill-label font-medium">No model</span>
              </button>
            ) : modelsLoaded ? (
              <Dropdown value={props.model} options={modelOptions} onChange={props.onModelChange} align="right" />
            ) : (
              <button
                type="button"
                className="pill chip text-faint cursor-default text-[12px]"
                disabled
                data-testid="models-loading"
                title="Fetching the model list from the server"
              >
                <span className="pill-label">Loading models...</span>
              </button>
            )}

            <VoiceButton
              ready={voiceReady}
              recording={voice.isListening}
              transcribing={voice.isTranscribing}
              disabled={props.running}
              onClick={handleVoiceToggle}
              onConfigure={props.onConfigureVoiceInput}
            />

            {props.running ? (
              <button
                type="button"
                className="btn danger px-3 py-1 bg-danger text-white rounded-md text-[13px] font-medium"
                onClick={props.onInterrupt}
              >
                Stop
              </button>
            ) : (
              <button
                type="button"
                className={
                  "w-7 h-7 rounded-full grid place-items-center shrink-0 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 " +
                  (hasContent && props.connected
                    ? "bg-accent text-white hover:brightness-110 shadow-sm"
                    : "bg-bg border border-border text-faint opacity-60")
                }
                onClick={submit}
                disabled={!props.connected || !hasContent}
                title={needsModel ? "Connect a model to send" : undefined}
                aria-label="Send"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </svg>
              </button>
            )}
          </div>
        )}
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {voice.isListening ? "Voice input is listening" : voice.isTranscribing ? "Transcribing voice input" : ""}
      </span>
    </div>
  );
}
