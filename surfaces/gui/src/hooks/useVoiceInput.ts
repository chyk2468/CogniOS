import { useCallback, useEffect, useRef, useState } from "react";
import { fetch as apiFetch, httpBase } from "../api/client";
import {
  cancelDictation,
  getDictationLevel,
  getDictationStatus,
  isTauri,
  startDictation,
  stopDictation,
  type DictationStatus,
} from "../tauri";

export type VoiceInputState =
  | "idle"
  | "listening"
  | "transcribing"
  | "error";

export type UseVoiceInputOptions = {
  onFinalTranscript?: (transcript: string) => void;
  onLivePartial?: (partial: string) => void;
};

const errorMessage = (error: unknown): string =>
  error instanceof Error ? error.message : typeof error === "string" ? error : "Voice input is unavailable.";

export function useVoiceInput(
  optionsOrHandler?: UseVoiceInputOptions | ((transcript: string) => void)
) {
  const options: UseVoiceInputOptions =
    typeof optionsOrHandler === "function"
      ? { onFinalTranscript: optionsOrHandler }
      : optionsOrHandler ?? {};

  const [state, setState] = useState<VoiceInputState>("idle");
  const [status, setStatus] = useState<DictationStatus | null>(null);
  const [levels, setLevels] = useState<number[]>([]);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const activeRef = useRef(false);
  const optionsRef = useRef(options);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaChunksRef = useRef<Blob[]>([]);
  const meterTimerRef = useRef<number | null>(null);

  useEffect(() => {
    optionsRef.current = options;
  });

  const refreshStatus = useCallback(async () => {
    if (!isTauri()) return null;
    const next = await getDictationStatus();
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const stopWebAudio = useCallback(() => {
    if (meterTimerRef.current) {
      window.clearInterval(meterTimerRef.current);
      meterTimerRef.current = null;
    }
    if (mediaRecorderRef.current) {
      try {
        if (mediaRecorderRef.current.state !== "inactive") {
          mediaRecorderRef.current.stop();
        }
      } catch {}
      mediaRecorderRef.current = null;
    }
    if (mediaStreamRef.current) {
      try {
        mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      } catch {}
      mediaStreamRef.current = null;
    }
    if (audioCtxRef.current) {
      try {
        void audioCtxRef.current.close();
      } catch {}
      audioCtxRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    activeRef.current = false;
    stopWebAudio();
    mediaChunksRef.current = [];
    setLevels([]);
    setSeconds(0);
  }, [stopWebAudio]);

  const startListening = useCallback(async () => {
    if (state === "listening" || state === "transcribing") return;
    setError(null);
    setLevels([]);
    setSeconds(0);

    // Browser audio recording via MediaRecorder + AnalyserNode (zero deprecated ScriptProcessorNode)
    if (!isTauri()) {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Microphone access is not supported in this environment.");
        }
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaStreamRef.current = stream;

        const AudioContextClass =
          window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const audioCtx = new AudioContextClass();
        audioCtxRef.current = audioCtx;

        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        if (meterTimerRef.current) window.clearInterval(meterTimerRef.current);
        meterTimerRef.current = window.setInterval(() => {
          if (!activeRef.current) return;
          analyser.getByteTimeDomainData(dataArray);
          let sumSquares = 0;
          for (let i = 0; i < dataArray.length; i++) {
            const val = (dataArray[i] - 128) / 128;
            sumSquares += val * val;
          }
          const rms = Math.sqrt(sumSquares / dataArray.length);
          const level = Math.min(1, rms * 6);
          setLevels((cur) => [...cur.slice(-18), level]);
        }, 100);

        mediaChunksRef.current = [];
        const mimeType =
          typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
            ? "audio/webm;codecs=opus"
            : typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported("audio/webm")
            ? "audio/webm"
            : "";

        const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        mediaRecorderRef.current = recorder;

        recorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0) {
            mediaChunksRef.current.push(e.data);
          }
        };

        recorder.start(100);

        activeRef.current = true;
        setState("listening");
        return;
      } catch (micErr) {
        if (typeof window !== "undefined" && !navigator.mediaDevices?.getUserMedia) {
          setState("listening");
          activeRef.current = true;
          return;
        }
        reset();
        setError(errorMessage(micErr));
        setState("error");
        return;
      }
    }

    try {
      const current = status ?? (await refreshStatus());
      if (!current) throw new Error("Voice input is unavailable.");
      if (!current.supported) throw new Error(current.compatibility_reason || "Voice input is not supported on this device.");
      if (!current.model_verified || !current.test_passed) {
        throw new Error("Set up and test Voice Input in Settings first.");
      }
      setState("listening");
      activeRef.current = true;
      const recording = await startDictation();
      setStatus(recording);
    } catch (startError) {
      reset();
      setError(errorMessage(startError));
      setState("error");
      void refreshStatus();
    }
  }, [refreshStatus, reset, state, status]);

  const stopListening = useCallback(async () => {
    if (!activeRef.current && state === "idle") return;
    activeRef.current = false;
    setState("transcribing");

    // In browser environment: finalize recorded audio and transcribe via whisper.cpp backend
    if (!isTauri()) {
      if (meterTimerRef.current) {
        window.clearInterval(meterTimerRef.current);
        meterTimerRef.current = null;
      }

      const recorder = mediaRecorderRef.current;
      const audioBlob = await new Promise<Blob>((resolve) => {
        if (!recorder || recorder.state === "inactive") {
          resolve(new Blob(mediaChunksRef.current, { type: "audio/webm" }));
          return;
        }
        recorder.onstop = () => {
          resolve(new Blob(mediaChunksRef.current, { type: recorder.mimeType || "audio/webm" }));
        };
        recorder.stop();
      });

      stopWebAudio();

      try {
        const res = await apiFetch(`${httpBase()}/v1/voice/transcribe`, {
          method: "POST",
          headers: {
            "Content-Type": audioBlob.type || "audio/webm",
          },
          body: audioBlob,
        });

        if (!res.ok) {
          throw new Error(`Transcription service error (${res.status})`);
        }

        const data = (await res.json()) as { ok: boolean; text?: string; error?: string };
        reset();
        setState("idle");
        if (data.ok && data.text) {
          optionsRef.current.onFinalTranscript?.(data.text);
        } else if (data.error) {
          setError(data.error);
        }
      } catch (fetchErr) {
        reset();
        setState("idle");
        setError(errorMessage(fetchErr));
      }
      return;
    }

    try {
      const finalText = (await stopDictation()).trim();
      reset();
      await refreshStatus();
      setState("idle");
      if (finalText) {
        optionsRef.current.onFinalTranscript?.(finalText);
      }
    } catch (stopError) {
      reset();
      setError(errorMessage(stopError));
      setState("error");
      void refreshStatus();
    }
  }, [refreshStatus, reset, state, stopWebAudio]);

  const cancel = useCallback(async () => {
    activeRef.current = false;
    stopWebAudio();
    if (isTauri()) {
      try {
        await cancelDictation();
      } catch {}
      await refreshStatus();
    }
    reset();
    setState("idle");
  }, [refreshStatus, reset, stopWebAudio]);

  const toggleListening = useCallback(() => {
    if (state === "listening") {
      void stopListening();
    } else if (state === "idle" || state === "error") {
      void startListening();
    }
  }, [startListening, state, stopListening]);

  // Duration timer
  useEffect(() => {
    if (state !== "listening") return;
    const timer = window.setInterval(() => setSeconds((cur) => cur + 1), 1000);
    return () => window.clearInterval(timer);
  }, [state]);

  // Meter audio levels while recording on Tauri native
  useEffect(() => {
    if (!isTauri() || state !== "listening") return;
    const timer = window.setInterval(() => {
      getDictationLevel().then((level) => {
        if (typeof level === "number") setLevels((cur) => [...cur.slice(-18), level]);
      });
    }, 100);
    return () => window.clearInterval(timer);
  }, [state]);

  useEffect(() => {
    return () => {
      activeRef.current = false;
      stopWebAudio();
      if (isTauri()) {
        void cancelDictation().catch(() => undefined);
      }
    };
  }, [stopWebAudio]);

  return {
    state,
    isListening: state === "listening",
    isTranscribing: state === "transcribing",
    isActive: state === "listening" || state === "transcribing",
    status,
    levels,
    seconds,
    error,
    startListening,
    stopListening,
    toggleListening,
    cancel,
    refreshStatus,
  };
}
