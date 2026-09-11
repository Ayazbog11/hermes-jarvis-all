"""Тесты plugins/jarvis-core/voice_note.py — синтез голосовых сообщений (обёртка над hud/tts.py)."""

from __future__ import annotations

import types

from conftest import load_plugin


def _core(monkeypatch):
    mod = load_plugin("jarvis-core")
    return mod


def test_generate_empty_text_returns_error(monkeypatch):
    core = _core(monkeypatch)
    r = core.voice_note.generate("")
    assert r["success"] is False
    assert "Пустой текст" in r["error"]


def test_generate_no_hud_tts_available(monkeypatch):
    core = _core(monkeypatch)
    monkeypatch.setattr(core.voice_note, "_load_hud_tts", lambda: None)
    r = core.voice_note.generate("Привет")
    assert r["success"] is False
    assert "hud/tts.py" in r["error"]


def test_generate_no_engine_available(monkeypatch):
    core = _core(monkeypatch)
    fake_tts = types.SimpleNamespace(synthesize=lambda text: None, engine=lambda: "none")
    monkeypatch.setattr(core.voice_note, "_load_hud_tts", lambda: fake_tts)
    r = core.voice_note.generate("Привет")
    assert r["success"] is False
    assert "движка TTS" in r["error"]


def test_generate_success_writes_file(monkeypatch, tmp_path):
    core = _core(monkeypatch)
    fake_tts = types.SimpleNamespace(synthesize=lambda text: (b"fake-audio-bytes", "audio/mpeg"), engine=lambda: "edge-tts")
    monkeypatch.setattr(core.voice_note, "_load_hud_tts", lambda: fake_tts)
    r = core.voice_note.generate("Слушаю, сэр.", out_dir=str(tmp_path))
    assert r["success"] is True
    assert r["path"].endswith(".mp3")
    from pathlib import Path

    assert Path(r["path"]).read_bytes() == b"fake-audio-bytes"


def test_generate_synth_exception_is_caught(monkeypatch):
    core = _core(monkeypatch)

    def boom(text):
        raise RuntimeError("edge-tts crashed")

    fake_tts = types.SimpleNamespace(synthesize=boom, engine=lambda: "edge-tts")
    monkeypatch.setattr(core.voice_note, "_load_hud_tts", lambda: fake_tts)
    r = core.voice_note.generate("Привет")
    assert r["success"] is False
    assert "Ошибка синтеза" in r["error"]
