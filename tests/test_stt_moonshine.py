"""Tests for the Useful Sensors Moonshine Tiny speech-to-text integration."""

import io
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from cogniwork.server.app import create_app
from cogniwork.stt import (
    MoonshineSTTEngine,
    get_model_dir,
    get_model_status,
    is_model_available,
    transcribe_audio,
)


def test_moonshine_model_availability():
    """Verifies that the Moonshine Tiny model directory is found and valid."""
    assert is_model_available(), "Moonshine Tiny model should be available in stt/moonshine-tiny"
    model_dir = get_model_dir()
    assert model_dir is not None
    assert (model_dir / "config.json").is_file()
    assert (model_dir / "model.safetensors").is_file()
    assert (model_dir / "tokenizer.json").is_file()


def test_moonshine_model_status():
    """Checks the metadata dictionary returned by get_model_status."""
    status = get_model_status()
    assert status["model_name"] == "Moonshine Tiny (English)"
    assert status["model_installed"] is True
    assert status["parameters"] == "27M"
    assert status["model_bytes"] > 100_000_000


def test_moonshine_engine_singleton():
    """Ensures that MoonshineSTTEngine returns a cached singleton instance."""
    engine1 = MoonshineSTTEngine.get_instance()
    engine2 = MoonshineSTTEngine.get_instance()
    assert engine1 is engine2


def test_moonshine_transcription_from_numpy():
    """Tests transcribing a numpy array input."""
    # Generate 1.0 second 16kHz sine wave audio (440Hz tone)
    sr = 16000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sine_wave = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    result = transcribe_audio(sine_wave, sample_rate=sr)
    assert isinstance(result, str)


def test_moonshine_transcription_from_wav_bytes():
    """Tests transcribing audio passed as raw in-memory WAV bytes."""
    sr = 16000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sine_wave = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    buf = io.BytesIO()
    sf.write(buf, sine_wave, sr, format="WAV")
    wav_bytes = buf.getvalue()

    result = transcribe_audio(wav_bytes)
    assert isinstance(result, str)


def test_moonshine_transcription_from_file(tmp_path: Path):
    """Tests transcribing audio saved in a file path."""
    sr = 16000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sine_wave = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    audio_file = tmp_path / "test_audio.wav"
    sf.write(str(audio_file), sine_wave, sr)

    result = transcribe_audio(audio_file)
    assert isinstance(result, str)


def test_voice_status_api_endpoint(tmp_path: Path):
    """Tests the /v1/voice/status REST API endpoint."""
    from cogniwork.server import SessionManager
    manager = SessionManager(workspace=tmp_path)
    app = create_app(manager=manager)
    client = TestClient(app)

    response = client.get("/v1/voice/status")
    assert response.status_code == 200
    data = response.json()
    assert data["model_name"] == "Moonshine Tiny (English)"
    assert data["model_installed"] is True


def test_voice_transcribe_api_endpoint(tmp_path: Path):
    """Tests the /v1/voice/transcribe REST API endpoint with WAV bytes."""
    from cogniwork.server import SessionManager
    manager = SessionManager(workspace=tmp_path)
    app = create_app(manager=manager)
    client = TestClient(app)

    sr = 16000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sine_wave = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    buf = io.BytesIO()
    sf.write(buf, sine_wave, sr, format="WAV")
    wav_bytes = buf.getvalue()

    response = client.post(
        "/v1/voice/transcribe",
        content=wav_bytes,
        headers={"Content-Type": "audio/wav"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "text" in data
    assert isinstance(data["text"], str)

