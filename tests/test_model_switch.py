"""Тесты scripts/model_switch.py::get_all()/_clean_config_value() — регрессия для бага
"Модель ИИ" на HUD, показывавшего буквальный текст вместо значения модели (Round-релиз 2.1.0+
живое тестирование пользователя). `hermes` подменяется фейковым бинарником, чтобы не требовать
реального CLI/сети.
"""

from __future__ import annotations

import importlib.util
import stat
import sys


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("jarvis_model_switch_get_all", "scripts/model_switch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_fake_hermes(tmp_path, stdout_text: str, returncode: int = 0):
    """Создать фейковый `hermes`-скрипт, который на `config get <key>` печатает stdout_text."""
    script = tmp_path / "hermes"
    if sys.platform == "win32":
        script = tmp_path / "hermes.cmd"
        script.write_text(f'@echo off\r\necho {stdout_text}\r\nexit /b {returncode}\r\n', encoding="utf-8")
    else:
        script.write_text(f"#!/bin/sh\necho '{stdout_text}'\nexit {returncode}\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_clean_config_value_strips_not_found_markers(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    # Regression: a raw "not found"/"not set"/"null" string from `hermes config get` must never
    # be treated as if it were an actual model id — the HUD widget rendered the literal text
    # "not found" as the model name because get_all() used to take out.stdout.strip() unconditionally.
    assert m._clean_config_value("not found") == ""
    assert m._clean_config_value("Config key not found") == ""
    assert m._clean_config_value("null") == ""
    assert m._clean_config_value("None") == ""
    assert m._clean_config_value("   ") == ""
    assert m._clean_config_value("") == ""


def test_clean_config_value_passes_through_real_model_id(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    assert m._clean_config_value("upstage/solar-pro4:free") == "upstage/solar-pro4:free"
    assert m._clean_config_value("  anthropic/claude-opus-4.8  ") == "anthropic/claude-opus-4.8"


def test_get_all_returns_real_value_when_hermes_found(monkeypatch, tmp_path):
    fake = _make_fake_hermes(tmp_path, "upstage/solar-pro4:free")
    m = load(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "_hermes_bin", lambda: str(fake))
    result = m.get_all()
    assert result["success"] is True
    assert result["values"]["chat_model"] == "upstage/solar-pro4:free"


def test_get_all_never_leaks_not_found_marker_into_values(monkeypatch, tmp_path):
    # Defends the exact bug seen live: an unset key must render as empty string (HUD placeholder),
    # never as the literal text a CLI might print for "no value".
    fake = _make_fake_hermes(tmp_path, "not found")
    m = load(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "_hermes_bin", lambda: str(fake))
    result = m.get_all()
    assert result["success"] is True
    for value in result["values"].values():
        assert value != "not found"
        assert value == ""


def test_get_all_reports_missing_hermes(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    monkeypatch.setattr(m, "_hermes_bin", lambda: None)
    result = m.get_all()
    assert result["success"] is False
    assert "hermes" in result["error"]


def test_subprocess_calls_force_utf8_encoding(monkeypatch, tmp_path):
    """Regression (v2.1.9-era bug): on Windows hermes.exe always forces its own stdout/stderr to
    UTF-8 at startup (hermes_cli/stdio.py::configure_windows_stdio()), regardless of the console's
    active code page. get_all()/set_value()/apply_profile() used to call subprocess.run(text=True)
    without an explicit encoding, so Python decoded the UTF-8 bytes using
    locale.getpreferredencoding() instead — cp1251 on a Russian-locale Windows box, producing
    mojibake or UnicodeDecodeError for any Cyrillic model name/value/error message. Every
    subprocess.run() call in this module must now pass encoding="utf-8" explicitly."""
    m = load(monkeypatch, tmp_path)
    fake = tmp_path / "hermes"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setattr(m, "_hermes_bin", lambda: str(fake))

    import subprocess as _subprocess

    calls = []

    def spy_run(*args, **kwargs):
        calls.append(kwargs)
        return _subprocess.CompletedProcess(args, 0, "тест", "")

    monkeypatch.setattr(m.subprocess, "run", spy_run)

    m.get_all()
    m.set_value("chat_model", "upstage/solar-pro4:free")
    m.save_profile("p1", {"model.default": "upstage/solar-pro4:free"})
    m.apply_profile("p1")

    assert calls, "subprocess.run было не вызвано — тест не проверил ничего"
    for kwargs in calls:
        assert kwargs.get("encoding") == "utf-8", f"вызов subprocess.run без encoding='utf-8': {kwargs}"
