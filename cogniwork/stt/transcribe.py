"""CLI transcription entrypoint for CogniOS Moonshine STT."""

import sys
from pathlib import Path

from cogniwork.stt.engine import transcribe_audio


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m cogniwork.stt.transcribe <audio_file_path>", file=sys.stderr)
        sys.exit(1)

    audio_path = Path(sys.argv[1])
    if not audio_path.is_file():
        print(f"Error: audio file '{audio_path}' does not exist", file=sys.stderr)
        sys.exit(1)

    try:
        transcript = transcribe_audio(audio_path)
        print(transcript)
    except Exception as exc:
        print(f"Transcription error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
