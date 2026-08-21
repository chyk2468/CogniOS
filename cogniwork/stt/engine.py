"""Moonshine Tiny speech-to-text engine for CogniOS.

Provides fast, local, offline English transcription using Useful Sensors'
Moonshine Tiny (27M parameters, ~108 MB safetensors).
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import soundfile as sf
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor


def _state_dir() -> Path:
    """Returns the platform-specific default state directory for CogniOS."""
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            return Path(app_data) / "CogniOS"
    home = Path.home()
    return home / ".cognios"


def get_model_candidates() -> list[Path]:
    """Returns candidate directories where the moonshine-tiny model may reside."""
    candidates: list[Path] = []

    # 1. Environment variable overrides
    env_override = os.environ.get("COGNIWORK_MOONSHINE_MODEL_PATH") or os.environ.get(
        "COWORKER_MOONSHINE_MODEL_PATH"
    )
    if env_override:
        candidates.append(Path(env_override).resolve())

    # 2. Project workspace path
    root_dir = Path(__file__).resolve().parent.parent.parent
    candidates.append(root_dir / "stt" / "moonshine-tiny")
    candidates.append(root_dir / "stt" / "models" / "moonshine-tiny")
    candidates.append(root_dir / "moonshine-tiny")

    # 3. Application state directory
    candidates.append(_state_dir() / "models" / "moonshine-tiny")

    # 4. Standard current working directory
    candidates.append(Path.cwd() / "stt" / "moonshine-tiny")
    candidates.append(Path.cwd() / "moonshine-tiny")

    return candidates


def get_model_dir() -> Optional[Path]:
    """Finds and returns the first valid moonshine-tiny model directory."""
    for candidate in get_model_candidates():
        if candidate.is_dir():
            config_file = candidate / "config.json"
            safetensors_file = candidate / "model.safetensors"
            if config_file.is_file() and safetensors_file.is_file():
                return candidate
    return None


def is_model_available() -> bool:
    """Returns True if the Moonshine model is found locally."""
    return get_model_dir() is not None


class MoonshineSTTEngine:
    """Singleton Speech-to-Text engine powered by Moonshine Tiny."""

    _instance: Optional[MoonshineSTTEngine] = None
    _lock = threading.Lock()

    def __init__(self, model_dir: Optional[Union[str, Path]] = None, device: Optional[str] = None):
        self._model_dir = Path(model_dir) if model_dir else get_model_dir()
        if self._model_dir is None:
            raise FileNotFoundError(
                "Moonshine Tiny model not found. Ensure 'stt/moonshine-tiny' is present."
            )
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._torch_dtype = torch.float32
        self._load_lock = threading.Lock()
        self._processor: Optional[AutoProcessor] = None
        self._model: Optional[AutoModelForSpeechSeq2Seq] = None

    @classmethod
    def get_instance(cls, model_dir: Optional[Union[str, Path]] = None) -> MoonshineSTTEngine:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(model_dir=model_dir)
            return cls._instance

    def _ensure_loaded(self) -> None:
        if self._processor is not None and self._model is not None:
            return
        with self._load_lock:
            if self._processor is None or self._model is None:
                if self._model_dir is None:
                    self._model_dir = get_model_dir()
                    if self._model_dir is None:
                        raise FileNotFoundError(
                            "Moonshine Tiny model not found. Ensure 'stt/moonshine-tiny' is present."
                        )
                self._processor = AutoProcessor.from_pretrained(str(self._model_dir))
                self._model = AutoModelForSpeechSeq2Seq.from_pretrained(
                    str(self._model_dir),
                    dtype=self._torch_dtype,
                ).to(self.device)
                self._model.eval()

    def load(self) -> None:
        """Eagerly loads the model into memory."""
        self._ensure_loaded()

    def _to_mono_16k(self, audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
        """Converts multi-channel audio to mono and resamples to 16,000 Hz."""
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=-1)
        audio_data = audio_data.astype(np.float32)

        # Normalize if integer ranges were passed
        max_val = np.max(np.abs(audio_data)) if len(audio_data) > 0 else 0.0
        if max_val > 1.0:
            audio_data = audio_data / max_val

        if sample_rate != 16000 and len(audio_data) > 0:
            target_len = int(len(audio_data) * 16000 / sample_rate)
            if target_len > 0:
                audio_data = np.interp(
                    np.linspace(0, len(audio_data), target_len, endpoint=False),
                    np.arange(len(audio_data)),
                    audio_data,
                ).astype(np.float32)

        return audio_data

    def _read_audio(self, audio: Union[bytes, str, Path, np.ndarray], sample_rate: Optional[int] = None) -> tuple[np.ndarray, int]:
        """Parses audio from multiple input types into a numpy array and sample rate."""
        if isinstance(audio, np.ndarray):
            return audio, sample_rate or 16000

        if isinstance(audio, (str, Path)):
            path = Path(audio)
            if not path.is_file():
                raise FileNotFoundError(f"Audio file not found: {path}")
            try:
                data, sr = sf.read(str(path), dtype="float32")
                return data, sr
            except Exception:
                # Fallback to ffmpeg for unsupported container formats
                return self._ffmpeg_decode(path.read_bytes())

        if isinstance(audio, bytes):
            # Try reading directly with soundfile (works for WAV, OGG, FLAC)
            try:
                data, sr = sf.read(io.BytesIO(audio), dtype="float32")
                return data, sr
            except Exception:
                return self._ffmpeg_decode(audio)

        raise ValueError(f"Unsupported audio input type: {type(audio)}")

    def _ffmpeg_decode(self, audio_bytes: bytes) -> tuple[np.ndarray, int]:
        """Decodes arbitrary container audio bytes (e.g. WebM, AAC, MP3) to 16kHz PCM using ffmpeg."""
        with tempfile.NamedTemporaryFile(suffix=".input", delete=False) as tmp_in:
            tmp_in.write(audio_bytes)
            tmp_in_path = tmp_in.name

        tmp_wav = tmp_in_path + ".16k.wav"
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                tmp_in_path,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_f32le",
                tmp_wav,
            ]
            subprocess.run(cmd, capture_output=True, check=True, timeout=15)
            data, sr = sf.read(tmp_wav, dtype="float32")
            return data, sr
        except Exception as exc:
            raise RuntimeError(f"Failed to decode audio with ffmpeg: {exc}") from exc
        finally:
            for p in [tmp_in_path, tmp_wav]:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

    def transcribe(
        self,
        audio: Union[bytes, str, Path, np.ndarray],
        sample_rate: Optional[int] = None,
    ) -> str:
        """Transcribes input audio and returns the text transcript."""
        self._ensure_loaded()
        assert self._processor is not None
        assert self._model is not None

        raw_data, sr = self._read_audio(audio, sample_rate=sample_rate)
        pcm_16k = self._to_mono_16k(raw_data, sr)

        # Ignore empty or ultra-short audio (< 0.25s)
        if len(pcm_16k) < 4000:
            return ""

        inputs = self._processor(pcm_16k, return_tensors="pt", sampling_rate=16000)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Cap token generation length according to audio duration to prevent hallucination loops
        token_limit_factor = 6.5 / 16000
        seq_lens = inputs["attention_mask"].sum(dim=-1)
        max_length = max(16, int((seq_lens * token_limit_factor).max().item()))

        with torch.no_grad():
            generated_ids = self._model.generate(**inputs, max_length=max_length)

        transcript = self._processor.decode(generated_ids[0], skip_special_tokens=True)
        return transcript.strip()


def transcribe_audio(
    audio: Union[bytes, str, Path, np.ndarray],
    sample_rate: Optional[int] = None,
    model_dir: Optional[Union[str, Path]] = None,
) -> str:
    """Convenience function to transcribe audio using the singleton Moonshine engine."""
    engine = MoonshineSTTEngine.get_instance(model_dir=model_dir)
    return engine.transcribe(audio, sample_rate=sample_rate)


def get_model_status() -> dict[str, Any]:
    """Returns metadata about the installed Moonshine model."""
    model_dir = get_model_dir()
    installed = model_dir is not None
    safetensors_bytes = 0
    if model_dir:
        st_path = model_dir / "model.safetensors"
        if st_path.is_file():
            safetensors_bytes = st_path.stat().st_size

    return {
        "model_name": "Moonshine Tiny (English)",
        "model_dir": str(model_dir) if model_dir else None,
        "model_installed": installed,
        "model_bytes": safetensors_bytes,
        "parameters": "27M",
        "device": "cuda" if torch.cuda.is_available() else "cpu",
    }
