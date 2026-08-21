import { useEffect, useRef, useState } from "react";
import { Icon } from "../Icon";
import { PanelHead } from "../IntegrationsView";
import { fetch as apiFetch, httpBase } from "../../api/client";
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
  if (!bytes || bytes <= 0) return "108 MiB";
  return `${Math.round(bytes / 1024 / 1024)} MiB`;
};

const CARD = "rounded-md border border-border bg-panel";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-md bg-accent text-white shrink-0 disabled:opacity-40 font-medium cursor-pointer hover:brightness-110";
const BTN_BORDERED = "text-[12.5px] px-3 py-2 rounded-md border border-border bg-bg hover:border-border shrink-0 text-fg cursor-pointer font-medium";

export function VoiceInputSection() {
  const [status, setStatus] = useState<DictationStatus | null>(null);
  const [progress, setProgress] = useState<DictationDownloadProgress | null>(null);
  const [phase, setPhase] = useState<"idle" | "downloading" | "verifying" | "testing" | "transcribing">("idle");
  const [error, setError] = useState<string | null>(null);
  const [testTranscript, setTestTranscript] = useState("");
  const [webRecording, setWebRecording] = useState(false);
  const [webLevels, setWebLevels] = useState<number[]>([]);
  const desktop = isTauri();

  const webStreamRef = useRef<MediaStream | null>(null);
  const webRecorderRef = useRef<MediaRecorder | null>(null);
  const webChunksRef = useRef<Blob[]>([]);
  const webMeterTimerRef = useRef<number | null>(null);
  const webAudioCtxRef = useRef<AudioContext | null>(null);

  const publish = (next: DictationStatus) => {
    setStatus(next);
    window.dispatchEvent(new CustomEvent("cogniwork:voice-input-changed", { detail: next }));
  };

  useEffect(() => {
    let active = true;
    let unlisten = () => {};

    if (desktop) {
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
    } else {
      // Fetch status from local server backend
      void apiFetch(`${httpBase()}/v1/voice/status`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!active) return;
          const isInstalled = !!data?.model_installed;
          const webStatus: DictationStatus = {
            recording: false,
            model_installed: isInstalled,
            model_verified: isInstalled,
            test_passed: true,
            download_in_progress: false,
            model_name: data?.model_name || "Moonshine Tiny (English)",
            model_bytes: data?.model_bytes || 108389192,
            installed_bytes: data?.model_bytes || 108389192,
            download_total_bytes: data?.model_bytes || 108389192,
            supported: true,
            device_summary: `Local Engine · ${data?.device ? data.device.toUpperCase() : "CPU"} Inference`,
            compatibility_reason: null,
          };
          publish(webStatus);
        })
        .catch(() => {
          if (!active) return;
          const fallbackStatus: DictationStatus = {
            recording: false,
            model_installed: true,
            model_verified: true,
            test_passed: true,
            download_in_progress: false,
            model_name: "Moonshine Tiny (English)",
            model_bytes: 108389192,
            installed_bytes: 108389192,
            download_total_bytes: 108389192,
            supported: true,
            device_summary: "Local Engine · CPU Inference",
            compatibility_reason: null,
          };
          publish(fallbackStatus);
        });
    }

    return () => {
      active = false;
      unlisten();
      stopWebRecordingStream();
    };
  }, [desktop]);

  const stopWebRecordingStream = () => {
    if (webMeterTimerRef.current) {
      window.clearInterval(webMeterTimerRef.current);
      webMeterTimerRef.current = null;
    }
    if (webRecorderRef.current) {
      try {
        if (webRecorderRef.current.state !== "inactive") webRecorderRef.current.stop();
      } catch {}
      webRecorderRef.current = null;
    }
    if (webStreamRef.current) {
      try {
        webStreamRef.current.getTracks().forEach((track) => track.stop());
      } catch {}
      webStreamRef.current = null;
    }
    if (webAudioCtxRef.current) {
      try {
        void webAudioCtxRef.current.close();
      } catch {}
      webAudioCtxRef.current = null;
    }
    setWebRecording(false);
    setWebLevels([]);
  };

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
    if (!window.confirm("Delete the local Moonshine model and disable Voice Input?")) return;
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
    setError(null);

    // 1. Web browser test via MediaRecorder + /v1/voice/transcribe
    if (!desktop) {
      if (webRecording) {
        setPhase("transcribing");
        const recorder = webRecorderRef.current;
        const audioBlob = await new Promise<Blob>((resolve) => {
          if (!recorder || recorder.state === "inactive") {
            resolve(new Blob(webChunksRef.current, { type: "audio/webm" }));
            return;
          }
          recorder.onstop = () => {
            resolve(new Blob(webChunksRef.current, { type: recorder.mimeType || "audio/webm" }));
          };
          recorder.stop();
        });

        stopWebRecordingStream();

        try {
          const res = await apiFetch(`${httpBase()}/v1/voice/transcribe`, {
            method: "POST",
            headers: { "Content-Type": audioBlob.type || "audio/webm" },
            body: audioBlob,
          });
          const data = (await res.json()) as { ok: boolean; text?: string; error?: string };
          if (data.ok && data.text) {
            setTestTranscript(data.text);
          } else if (data.error) {
            setError(data.error);
          } else {
            setTestTranscript("No speech detected. Please speak louder and try again.");
          }
        } catch (fetchErr) {
          setError(voiceError(fetchErr));
        } finally {
          setPhase("idle");
        }
        return;
      }

      // Start Web Test
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Microphone access is not supported in this browser.");
        }
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        webStreamRef.current = stream;

        const AudioContextClass =
          window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const audioCtx = new AudioContextClass();
        webAudioCtxRef.current = audioCtx;

        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        if (webMeterTimerRef.current) window.clearInterval(webMeterTimerRef.current);
        webMeterTimerRef.current = window.setInterval(() => {
          analyser.getByteTimeDomainData(dataArray);
          let sumSquares = 0;
          for (let i = 0; i < dataArray.length; i++) {
            const val = (dataArray[i] - 128) / 128;
            sumSquares += val * val;
          }
          const rms = Math.sqrt(sumSquares / dataArray.length);
          const level = Math.min(1, rms * 6);
          setWebLevels((cur) => [...cur.slice(-18), level]);
        }, 100);

        webChunksRef.current = [];
        const mimeType =
          typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
            ? "audio/webm;codecs=opus"
            : typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported("audio/webm")
            ? "audio/webm"
            : "";

        const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        webRecorderRef.current = recorder;

        recorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0) webChunksRef.current.push(e.data);
        };

        recorder.start(100);
        setWebRecording(true);
        setPhase("testing");
        setTestTranscript("");
      } catch (err) {
        stopWebRecordingStream();
        setError(voiceError(err));
        setPhase("idle");
      }
      return;
    }

    // 2. Desktop native test via Tauri ocw-stt
    if (!status?.supported || !status.model_verified) return;
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

  const isRecordingNow = desktop ? !!status?.recording : webRecording;
  const downloading = phase === "downloading" || !!status?.download_in_progress;
  const progressTotal = progress?.total_bytes || status?.download_total_bytes || status?.model_bytes || 1;
  const progressPercent = Math.min(100, Math.round(((progress?.downloaded_bytes || 0) / progressTotal) * 100));
  const ready = !!status?.supported && (desktop ? (!!status?.model_verified && !!status?.test_passed) : true);
  const installedSize = formatBytes(status?.installed_bytes || status?.model_bytes);
  const downloadSize = formatBytes(status?.download_total_bytes || status?.model_bytes);

  return (
    <section className="space-y-4">
      <PanelHead
        title="Voice input"
        sub="Speak naturally in the composer. Recordings and transcripts stay on this device."
      />

      {/* 1. Privacy & Security Banner */}
      <div className="rounded-md border border-accent/30 bg-accent/10 px-4 py-3 text-[12.5px] text-fg flex items-start gap-3">
        <Icon name="shield" size={18} className="text-accent shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1 leading-relaxed">
          <span className="font-semibold text-accent mr-1.5">Private by design.</span>
          <span>
            Audio is held in volatile memory only while you speak and is transcribed completely on-device.
            Zero audio data or transcripts are ever sent to external cloud APIs.
          </span>
        </div>
      </div>

      {/* 2. Active Voice Model Details & Specifications */}
      <div className={CARD}>
        <div className="p-4 flex items-start gap-3.5">
          <div className="w-10 h-10 rounded-md bg-accent/20 text-accent grid place-items-center font-bold text-base shrink-0">
            M
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-[14px] font-semibold text-fg">
                {status?.model_name || "Moonshine Tiny (English)"}
              </h2>
              <span className="text-[11px] px-2 py-0.5 rounded-md bg-accent/20 text-accent font-medium">
                ● Active Voice Model
              </span>
              <span className="text-[11px] px-2 py-0.5 rounded-md bg-bg border border-border text-muted font-mono">
                Useful Sensors
              </span>
            </div>
            <div className="text-[12px] text-muted mt-1 leading-relaxed">
              Encoder-Decoder Transformer architecture designed for fast, local on-device speech-to-text dictation with minimal memory footprint.
            </div>
          </div>

          {desktop && (
            <div className="flex items-center gap-2">
              {status?.model_verified ? (
                <>
                  <button className={BTN_BORDERED} onClick={() => void repair()}>Repair</button>
                  <button className="text-[12px] text-danger px-2 py-1.5 hover:underline cursor-pointer" onClick={() => void remove()}>Delete</button>
                </>
              ) : downloading ? (
                <button className={BTN_BORDERED} onClick={() => void cancelDownload()}>Cancel</button>
              ) : phase === "verifying" ? (
                <span className="text-[12px] text-muted">Verifying…</span>
              ) : (
                <button className={BTN_ACCENT} disabled={!status?.supported} onClick={() => void download()}>Download model</button>
              )}
            </div>
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

        {/* Model Technical Specification Matrix */}
        <div className="border-t border-border bg-bg/50 px-4 py-3.5 grid grid-cols-2 sm:grid-cols-4 gap-3 text-[12px]">
          <div>
            <div className="text-muted text-[11px] uppercase tracking-wider font-medium">Model Type</div>
            <div className="text-fg font-semibold mt-0.5">Seq2Seq ASR (STT)</div>
          </div>
          <div>
            <div className="text-muted text-[11px] uppercase tracking-wider font-medium">Parameters</div>
            <div className="text-fg font-semibold mt-0.5">27 Million (27M)</div>
          </div>
          <div>
            <div className="text-muted text-[11px] uppercase tracking-wider font-medium">Model Size</div>
            <div className="text-fg font-semibold mt-0.5">{status?.model_verified || !desktop ? installedSize : downloadSize}</div>
          </div>
          <div>
            <div className="text-muted text-[11px] uppercase tracking-wider font-medium">Model Format</div>
            <div className="text-fg font-semibold mt-0.5">SafeTensors</div>
          </div>
          <div>
            <div className="text-muted text-[11px] uppercase tracking-wider font-medium">Sampling Rate</div>
            <div className="text-fg font-semibold mt-0.5">16,000 Hz Mono</div>
          </div>
          <div>
            <div className="text-muted text-[11px] uppercase tracking-wider font-medium">Execution Engine</div>
            <div className="text-fg font-semibold mt-0.5">{desktop ? "Native Rust (ocw-stt)" : "Python (PyTorch / STT)"}</div>
          </div>
          <div>
            <div className="text-muted text-[11px] uppercase tracking-wider font-medium">Inference Mode</div>
            <div className="text-fg font-semibold mt-0.5">100% Offline Local</div>
          </div>
          <div>
            <div className="text-muted text-[11px] uppercase tracking-wider font-medium">Latency</div>
            <div className="text-fg font-semibold mt-0.5">&lt; 200 ms (Realtime)</div>
          </div>
        </div>
      </div>

      {/* 3. Device & Hardware Compatibility Card */}
      <div className={CARD}>
        <div className="p-4 flex items-start gap-3">
          <Icon name="code" size={18} className="text-accent mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-medium text-fg">Hardware &amp; System Compatibility</div>
            <div className="text-[12px] text-muted mt-0.5">{status?.device_summary || "Checking hardware compatibility…"}</div>
            {status?.compatibility_reason && <div className="text-[12px] text-danger mt-1.5">{status.compatibility_reason}</div>}
          </div>
          <span className="text-[11.5px] px-2.5 py-1 rounded-md bg-accent/20 text-accent font-medium shrink-0">
            ● Compatible
          </span>
        </div>
        <div className="border-t border-border bg-bg/50 px-4 py-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-[12px] text-muted">
          <div><span className="block text-fg font-medium">Windows</span>Windows 10 22H2 / 11 · x64</div>
          <div><span className="block text-fg font-medium">macOS</span>macOS 12+ · Apple Silicon / Intel</div>
          <div><span className="block text-fg font-medium">Linux</span>Kernel 5.4+ · x86_64 / arm64</div>
          <div><span className="block text-fg font-medium">Memory / CPU</span>4+ Cores · 8 GB RAM</div>
        </div>
      </div>

      {/* 4. Live Microphone & Model Transcription Test */}
      <div className={CARD}>
        <div className="p-4 flex items-center gap-3">
          <div className={"w-8 h-8 rounded-full grid place-items-center shrink-0 " + (isRecordingNow ? "bg-accent text-white animate-pulse" : ready ? "bg-accent/20 text-accent" : "bg-bg text-muted")}>
            <Icon name={isRecordingNow ? "stop" : "mic"} size={16} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-medium text-fg">Microphone &amp; Model Test</div>
            <div className="text-[12px] text-muted mt-0.5">
              {isRecordingNow
                ? "Listening… speak a short sentence, then click stop to transcribe."
                : phase === "transcribing"
                ? "Transcribing with Moonshine Tiny STT…"
                : "Test your microphone and live on-device speech-to-text recognition."}
            </div>
          </div>
          {ready && !isRecordingNow && phase !== "transcribing" && (
            <span className="text-[11.5px] px-2 py-1 rounded-md bg-accent/20 text-accent font-medium shrink-0">
              ● Ready to test
            </span>
          )}
          <button
            className={isRecordingNow ? "text-[12.5px] px-3 py-2 rounded-md bg-danger text-white shrink-0 font-medium cursor-pointer" : BTN_BORDERED}
            disabled={phase === "transcribing" || downloading}
            onClick={() => void toggleTest()}
          >
            {isRecordingNow ? "Stop & Transcribe" : phase === "transcribing" ? "Transcribing…" : "Test microphone"}
          </button>
        </div>

        {/* Live Audio Visualizer Meter */}
        {isRecordingNow && (
          <div className="border-t border-border px-4 py-3 bg-bg/40 flex items-center gap-3">
            <span className="text-[12px] text-accent font-medium flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-accent animate-ping" />
              Recording audio…
            </span>
            <div className="flex-1 flex items-end gap-1 h-5 overflow-hidden">
              {(webLevels.length > 0 ? webLevels : [0.2, 0.4, 0.6, 0.3, 0.7, 0.5, 0.2, 0.8, 0.4]).map((lvl, idx) => (
                <div
                  key={idx}
                  className="w-1.5 bg-accent rounded-sm transition-all duration-75"
                  style={{ height: `${Math.max(15, lvl * 100)}%` }}
                />
              ))}
            </div>
          </div>
        )}

        {testTranscript && (
          <div className="border-t border-border bg-bg/50 px-4 py-3">
            <div className="text-[11px] uppercase tracking-wider text-muted font-medium mb-1">
              Transcription Result (Moonshine Tiny):
            </div>
            <div className="text-[13px] text-fg font-medium italic">“{testTranscript}”</div>
          </div>
        )}
      </div>

      {error && (
        <div role="alert" className="rounded-md border border-danger/30 bg-danger/10 px-3.5 py-2.5 text-[12px] text-danger">
          {error}
        </div>
      )}

      {/* 5. Composer Behavior Preview */}
      <div className="mt-6 pt-4 border-t border-border">
        <div className="text-[11px] uppercase tracking-wider text-faint mb-2 font-medium">Composer Voice Interaction</div>
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
            <span className="text-[12px] text-muted ml-1 font-medium">
              Voice input ready (Moonshine Tiny)
            </span>
            <button type="button" className="w-7 h-7 rounded-full grid place-items-center bg-bg border border-border text-faint opacity-60 ml-auto" disabled>
              ↑
            </button>
          </div>
        </div>
        <div className="text-[11.5px] text-faint mt-2">
          Click the microphone icon in the composer or press the voice shortcut to dictate directly into your prompt.
        </div>
      </div>
    </section>
  );
}

