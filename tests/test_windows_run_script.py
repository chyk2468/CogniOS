from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_run_script_uses_safe_local_launcher():
    script = (ROOT / "run.bat").read_text(encoding="utf-8")
    lowered = script.lower()

    assert 'pushd "%~dp0"' in lowered
    assert ".venv\\scripts\\python.exe" in lowered
    assert "launcher.py" in lowered


def test_run_ai_bat_delegates_to_run_bat():
    script = (ROOT / "run_ai.bat").read_text(encoding="utf-8")
    lowered = script.lower()

    assert 'run.bat' in lowered
