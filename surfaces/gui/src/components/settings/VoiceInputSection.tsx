import { useEffect, useState } from "react";
import { Icon } from "../Icon";
import { PanelHead } from "../IntegrationsView";
import {
  cancelDictationModelDownload,
  deleteDictationModel,
  downloadDictationModel,
  getDictationStatus,
  isTauri,
  listenDictationDownloadProgress,
  markDictationTestPassed,
  startDictation,
  stopDictation,
  verifyDictationModel,
  type DictationDownloadProgress,
  type DictationStatus,
} from "../../tauri";

const voiceError = (error: unknown) =>
  error instanceof Error ? error.message : typeof error === "string" ? error : "Voice Input could not complete that action.";

const formatBytes = (bytes?: number) => {
  if (!bytes || bytes <= 0) return "0 MiB";
  return `${Math.round(bytes / 1024 / 1024)} MiB`;
};

const CARD = "rounded-md border border-border bg-panel";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-md bg-accent text-white shrink-0 disabled:opacity-40 font-medium cursor-pointer hover:brightness-110";
const BTN_BORDERED = "text-[12.5px] px-3 py-2 rounded-md border border-border bg-bg hover:border-border shrink-0 text-fg cursor-pointer";

export function VoiceInputSection() {
  const [status, setStatus] = useState<DictationStatus | null>(null);
  const [progress, setProgress] = useState<DictationDownloadProgress | null>(null);
  const [phase, setPhase] = useState<"idle" | "downloading" | "verifying" | "testing" | "transcribing">("idle");
  const [error, setError] = useState<string | null>(null);
  const [testTranscript, setTestTranscript] = useState("");
  const desktop = isTauri();

  const publish = (next: DictationStatus) => {
    setStatus(next);
    window.dispatchEvent(new CustomEvent("cogniwork:voice-input-changed", { detail: next }));
  };

  useEffect(() => {
    if (!desktop) return;
    let active = true;
    let unlisten = () => {};
    void listenDictationDownloadProgress((next) => {
      if (active) setProgress(next);
    }).then((stop) => {
      unlisten = stop;
    });
    void getDictationStatus().then(async (initial) => {
      if (!active || !initial) return;
      publish(initial);
      if (initial.model_installed && !initial.model_verified) {
        setPhase("verifying");
        try {
          const verified = await verifyDictationModel();
          if (active) publish(verified);
        } catch (verifyError) {
          if (active) setError(voiceError(verifyError));
        } finally {
          if (active) setPhase("idle");
        }
      }
    });
    return () => {
      active = false;
      unlisten();
    };
  }, [desktop]);

  const download = async () => {
    setError(null);
    setProgress({ downloaded_bytes: 0, total_bytes: status?.download_total_bytes || status?.model_bytes || 0 });
    setPhase("downloading");
    try {
      publish(await downloadDictationModel());
    } catch (downloadError) {
      setError(voiceError(downloadError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  const cancelDownload = async () => {
    await cancelDictationModelDownload().catch(() => undefined);
  };

  const repair = async () => {
    setError(null);
    try {
      publish(await deleteDictationModel());
      await download();
    } catch (repairError) {
      setError(voiceError(repairError));
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete the local Whisper model and disable Voice Input?")) return;
    setError(null);
    try {
      publish(await deleteDictationModel());
      setTestTranscript("");
      setProgress(null);
    } catch (deleteError) {
      setError(voiceError(deleteError));
    }
  };

  const toggleTest = async () => {
    if (!status?.supported || !status.model_verified) return;
    setError(null);
    try {
      if (status.recording) {
        setPhase("transcribing");
        const transcript = (await stopDictation()).trim();
        setTestTranscript(transcript);
        if (!transcript) throw new Error("No speech was detected. Try again and speak for a little longer.");
        publish(await markDictationTestPassed());
      } else {
        setTestTranscript("");
        setPhase("testing");
        publish(await startDictation());
      }
    } catch (testError) {
      setError(voiceError(testError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  const downloading = phase === "downloading" || !!status?.download_in_progress;
  const progressTotal = progress?.total_bytes || status?.download_total_bytes || status?.model_bytes || 1;
  const progressPercent = Math.min(100, Math.round(((progress?.downloaded_bytes || 0) / progressTotal) * 100));
  const ready = !!status?.supported && !!status?.model_verified && !!status?.test_passed;
  const installedSize = formatBytes(status?.installed_bytes || status?.model_bytes);
  const downloadSize = formatBytes(status?.download_total_bytes || status?.model_bytes);

  return (
    <section>
      <PanelHead
        title="Voice input"
        sub="Speak naturally in the composer. Recordings and transcripts stay on this device."
      />

      {!desktop ? (
        <div className={CARD + " p-4 text-[13px] text-muted"}>Voice Input setup is available in the CogniOS desktop app.</div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-md border border-accent/30 bg-accent/10 px-4 py-3 text-[12.5px] text-fg flex items-center gap-2">
            <span className="font-semibold text-accent">Private by design.</span>
            <span>Audio is held in memory only while you record and is transcribed locally.</span>
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-start gap-3">
              <Icon name="code" size={18} className="text-accent mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium text-fg">This device is supported</div>
                <div className="text-[12px] text-muted mt-1">{status?.device_summary || "Checking compatibility…"}</div>
                {status?.compatibility_reason && <div className="text-[12px] text-danger mt-1.5">{status.compatibility_reason}</div>}
              </div>
              {status && (
                <span className={"text-[11.5px] px-2 py-1 rounded-md " + (status.supported ? "bg-accent/20 text-accent font-medium" : "bg-danger/20 text-danger")}>
                  {status.supported ? "● Compatible" : "Unsupported"}
                </span>
              )}
            </div>
            <div className="border-t border-border bg-bg/50 px-4 py-3 grid grid-cols-2 gap-3 text-[12px] text-muted">
              <div><span className="block text-fg font-medium">Mac</span>macOS 12+ · Apple Silicon M1+</div>
              <div><span className="block text-fg font-medium">Windows</span>Windows 10 22H2/11 · x64</div>
              <div><span className="block text-fg font-medium">Memory</span>8 GB recommended</div>
              <div><span className="block text-fg font-medium">Processor</span>4 CPU cores recommended</div>
            </div>
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <div className="w-9 h-9 rounded-md bg-accent/20 text-accent grid place-items-center font-semibold">W</div>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium text-fg">{status?.model_name || "Whisper Large v3 Turbo (q5_0)"}</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {status?.model_verified
                    ? `Installed and verified · ${installedSize}`
                    : `Fast local transcription · Download size ${downloadSize}`}
                </div>
              </div>
              {status?.model_verified ? (
                <>
                  <span className="text-[11.5px] px-2 py-1 rounded-md bg-accent/20 text-accent font-medium">● Ready</span>
                  <button className={BTN_BORDERED} onClick={() => void repair()}>Repair</button>
                  <button className="text-[12px] text-danger px-2 py-2 hover:underline cursor-pointer" onClick={() => void remove()}>Delete</button>
                </>
              ) : downloading ? (
                <button className={BTN_BORDERED} onClick={() => void cancelDownload()}>Cancel</button>
              ) : phase === "verifying" ? (
                <span className="text-[12px] text-muted">Verifying…</span>
              ) : (
                <button className={BTN_ACCENT} disabled={!status?.supported} onClick={() => void download()}>Download model</button>
              )}
            </div>
            {downloading && (
              <div className="border-t border-border px-4 py-3">
                <div className="h-1.5 rounded-md bg-line overflow-hidden">
                  <div className="h-full bg-accent transition-all" style={{ width: `${progressPercent}%` }} />
                </div>
                <div className="mt-1.5 text-[11.5px] text-muted flex">
                  <span>{formatBytes(progress?.downloaded_bytes || 0)} of {formatBytes(progressTotal)}</span>
                  <span className="ml-auto">{progressPercent}%</span>
                </div>
              </div>
            )}
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <Icon name="mic" size={18} className={ready ? "text-accent" : "text-muted"} />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium text-fg">Microphone test</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {ready ? "Your microphone and local transcription engine are working." : "Available after the model is downloaded and verified."}
                </div>
              </div>
              {ready && <span className="text-[11.5px] px-2 py-1 rounded-md bg-accent/20 text-accent font-medium">● Passed</span>}
              <button className={BTN_BORDERED} disabled={!status?.supported || !status?.model_verified || phase === "transcribing"} onClick={() => void toggleTest()}>
                {status?.recording ? "Stop and check" : phase === "transcribing" ? "Transcribing…" : ready ? "Test again" : "Test microphone"}
              </button>
            </div>
            {status?.recording && <div className="border-t border-border px-4 py-3 text-[12px] text-accent font-medium" role="status">● Listening… speak a short phrase, then click stop.</div>}
            {testTranscript && <div className="border-t border-border bg-bg/50 px-4 py-3 text-[13px] text-fg italic">“{testTranscript}”</div>}
          </div>

          {error && <div role="alert" className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2.5 text-[12px] text-danger">{error}</div>}

          {/* §37 Composer behavior in this state */}
          <div className="mt-6 pt-4 border-t border-border">
            <div className="text-[11px] uppercase tracking-wider text-faint mb-2 font-medium">Composer behavior in this state</div>
            <div className="rounded-md border border-border bg-panel p-3.5 shadow-sm">
              <div className="text-faint text-[13px] min-h-[36px]">Ask CogniOS anything…</div>
              <div className="flex items-center gap-1.5 pt-1">
                <button type="button" className="w-7 h-7 rounded-md grid place-items-center text-muted" disabled>＋</button>
                <span className="text-[12px] text-muted px-2 py-0.5 rounded-md bg-bg border border-border">Ask for approval⌄</span>
                <span className="flex-1" />
                <button
                  type="button"
                  className={"w-7 h-7 grid place-items-center rounded-md relative " + (ready ? "text-accent" : "text-faint bg-bg")}
                  disabled
                >
                  <Icon name="mic" size={16} />
                </button>
                <span className="text-[12px] text-muted ml-1">
                  {ready ? "Voice input ready" : downloading ? "Voice model is downloading" : "Voice input needs setup"}
                </span>
                <button type="button" className="w-7 h-7 rounded-full grid place-items-center bg-bg border border-border text-faint opacity-60 ml-auto" disabled>
                  ↑
                </button>
              </div>
            </div>
            <div className="text-[11.5px] text-faint mt-2">
              {ready
                ? "Voice input is ready. Click the microphone icon in the composer to record."
                : "Before Ready, the muted mic opens this Settings section. After Ready it becomes the normal record/stop control."}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
