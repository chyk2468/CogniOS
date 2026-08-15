import { Icon } from "../Icon";

type Props = {
  ready: boolean;
  recording?: boolean;
  transcribing?: boolean;
  disabled?: boolean;
  onClick: () => void;
  onConfigure?: () => void;
};

export function VoiceButton({ ready, recording, transcribing, disabled, onClick, onConfigure }: Props) {
  const label = recording
    ? "Stop voice input"
    : transcribing
    ? "Transcribing voice input"
    : ready
    ? "Start voice input"
    : "Configure Voice Input in Settings";

  const btnClass =
    "composer-voice-btn relative w-7 h-7 grid place-items-center rounded-md transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 " +
    (recording
      ? "voice-btn-recording bg-dangerSoft text-danger"
      : transcribing
      ? "voice-btn-busy bg-accentSoft text-accent cursor-wait"
      : ready
      ? "voice-btn-ready text-accent hover:bg-accentSoft/60"
      : "voice-btn-locked text-faint hover:bg-bg hover:text-muted");

  return (
    <button
      type="button"
      className={btnClass}
      title={recording ? "Stop recording (Esc to cancel)" : transcribing ? "Transcribing…" : ready ? "Voice input (Speak to type)" : "Configure Voice Input in Settings"}
      aria-label={label}
      aria-disabled={!ready || transcribing || disabled ? "true" : undefined}
      aria-pressed={recording ? "true" : "false"}
      disabled={disabled || transcribing}
      onClick={() => {
        if (recording) {
          onClick();
        } else if (ready && !transcribing) {
          onClick();
        } else if (!ready) {
          onConfigure?.();
        }
      }}
    >
      <Icon name="mic" size={16} />
      {!ready && !recording && !transcribing && (
        <span className="voice-tip" role="tooltip">Configure Voice Input in Settings</span>
      )}
    </button>
  );
}
