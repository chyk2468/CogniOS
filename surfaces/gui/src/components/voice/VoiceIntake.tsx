import type { VoiceInputState } from "../../hooks/useVoiceInput";
import { Icon } from "../Icon";

type Props = {
  state: VoiceInputState;
  transcript: string;
  partial?: string;
  levels: number[];
  seconds: number;
  onStop: () => void;
  onCancel: () => void;
};

const labelForState = (state: VoiceInputState) => {
  if (state === "transcribing") return "Transcribing";
  return "Listening";
};

const formatTime = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export function VoiceIntake({ state, transcript, partial, levels, seconds, onStop, onCancel }: Props) {
  if (state === "idle" || state === "error") return null;
  const busy = state === "transcribing";
  const text = [transcript, partial].filter(Boolean).join(" ").trim();

  return (
    <div className="voice-intake" role="region" aria-label="Voice input is listening">
      <div className="voice-intake-main">
        <div className="voice-intake-status">
          <span className="voice-mic-ring" aria-hidden="true">
            <Icon name="mic" size={18} />
          </span>
          <VoiceWaveform levels={levels} active={!busy} />
          <span className="voice-state-label">{labelForState(state)}</span>
        </div>
        <div className="voice-live-transcript" aria-live="polite">
          {text ? (
            <>
              {transcript && <span>{transcript}</span>}
              {partial && <span className="voice-partial"> {partial}</span>}
            </>
          ) : (
            <span className="voice-placeholder">Speak now…</span>
          )}
        </div>
      </div>
      <div className="voice-intake-controls">
        <button
          type="button"
          className="voice-stop-btn"
          onClick={onStop}
          disabled={busy}
          aria-label="Stop voice input"
        >
          <span aria-hidden="true">■</span>
          Stop
        </button>
        <button
          type="button"
          className="voice-cancel-btn"
          onClick={onCancel}
          disabled={busy}
          aria-label="Cancel voice input"
        >
          Cancel
        </button>
        <span className="voice-footer-state">{labelForState(state)}</span>
        <span className="voice-timer" aria-label={`Recording time ${formatTime(seconds)}`}>
          {formatTime(seconds)}
        </span>
      </div>
    </div>
  );
}

function VoiceWaveform({ levels, active }: { levels: number[]; active: boolean }) {
  const bars = Array.from({ length: 9 }, (_, index) => levels[levels.length - 9 + index] ?? 0.08);
  return (
    <span className="voice-wave-bars" aria-hidden="true" data-active={active ? "true" : "false"}>
      {bars.map((level, index) => (
        <i key={index} style={{ transform: `scaleY(${Math.max(0.18, level * 1.8)})` }} />
      ))}
    </span>
  );
}
