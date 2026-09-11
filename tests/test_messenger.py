"""Тесты plugins/jarvis-core/messenger.py — обёртка над `hermes send`, без реального hermes/сети."""

from __future__ import annotations

import json
import subprocess

import pytest

from conftest import load_plugin


@pytest.fixture()
def core(monkeypatch):
    mod = load_plugin("jarvis-core")
    mod.messenger.reset_cache()
    yield mod
    mod.messenger.reset_cache()


def test_is_available_false_without_hermes(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: None)
    core.messenger.reset_cache()
    assert core.messenger.is_available() is False


def test_is_available_true_and_cached(monkeypatch, core):
    calls = []

    def fake_which(name):
        calls.append(name)
        return "/usr/local/bin/hermes"

    monkeypatch.setattr(core.messenger.shutil, "which", fake_which)
    core.messenger.reset_cache()
    assert core.messenger.is_available() is True
    assert core.messenger.is_available() is True
    assert len(calls) == 1  # закэшировано


def test_send_without_hermes_binary(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: None)
    r = core.messenger.send("telegram", "привет")
    assert r["success"] is False
    assert "hermes" in r["error"]


def test_send_empty_target_or_text(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")
    assert core.messenger.send("", "текст")["success"] is False
    assert core.messenger.send("telegram", "")["success"] is False


def test_send_success(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")

    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["/bin/hermes", "send", "--to"]
        assert "телеграм-тест" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"message_id": "42"}), stderr="")

    monkeypatch.setattr(core.messenger.subprocess, "run", fake_run)
    r = core.messenger.send("telegram", "телеграм-тест", subject="Заголовок")
    assert r["success"] is True
    assert r["message_id"] == "42"


def test_send_delivery_failure_exit_1(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="auth failed")

    monkeypatch.setattr(core.messenger.subprocess, "run", fake_run)
    r = core.messenger.send("telegram:12345", "hi")
    assert r["success"] is False
    assert "auth failed" in r["error"]


def test_send_usage_error_exit_2_adds_hint(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="unknown platform")

    monkeypatch.setattr(core.messenger.subprocess, "run", fake_run)
    r = core.messenger.send("bogus", "hi")
    assert r["success"] is False
    assert "hermes send --list" in r["error"]


def test_send_timeout(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 20))

    monkeypatch.setattr(core.messenger.subprocess, "run", fake_run)
    r = core.messenger.send("telegram", "hi")
    assert r["success"] is False
    assert "не ответил" in r["error"]


def test_send_file_without_hermes_binary(monkeypatch, core, tmp_path):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: None)
    p = tmp_path / "voice.mp3"
    p.write_bytes(b"fake-audio")
    r = core.messenger.send_file("telegram", str(p))
    assert r["success"] is False
    assert "hermes" in r["error"]


def test_send_file_missing_file(monkeypatch, core, tmp_path):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")
    r = core.messenger.send_file("telegram", str(tmp_path / "nope.mp3"))
    assert r["success"] is False
    assert "не найден" in r["error"]


def test_send_file_empty_target_or_path(monkeypatch, core, tmp_path):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")
    p = tmp_path / "voice.mp3"
    p.write_bytes(b"fake-audio")
    assert core.messenger.send_file("", str(p))["success"] is False
    assert core.messenger.send_file("telegram", "")["success"] is False


def test_send_file_success_uses_media_directive(monkeypatch, core, tmp_path):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")
    p = tmp_path / "voice.mp3"
    p.write_bytes(b"fake-audio")

    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["/bin/hermes", "send", "--to"]
        assert any(f"MEDIA:{p}" in part for part in cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"message_id": "7"}), stderr="")

    monkeypatch.setattr(core.messenger.subprocess, "run", fake_run)
    r = core.messenger.send_file("telegram", str(p), caption="Голосовое")
    assert r["success"] is True
    assert r["message_id"] == "7"


def test_send_file_delivery_failure(monkeypatch, core, tmp_path):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")
    p = tmp_path / "photo.png"
    p.write_bytes(b"fake-png")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="upload failed")

    monkeypatch.setattr(core.messenger.subprocess, "run", fake_run)
    r = core.messenger.send_file("telegram", str(p))
    assert r["success"] is False
    assert "upload failed" in r["error"]


def test_list_targets_success(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: "/bin/hermes")

    def fake_run(cmd, **kwargs):
        assert "--list" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps([{"platform": "telegram", "chat_id": "home"}]), stderr="")

    monkeypatch.setattr(core.messenger.subprocess, "run", fake_run)
    r = core.messenger.list_targets()
    assert r["success"] is True
    assert r["targets"][0]["platform"] == "telegram"


def test_list_targets_without_hermes(monkeypatch, core):
    monkeypatch.setattr(core.messenger.shutil, "which", lambda _: None)
    r = core.messenger.list_targets()
    assert r["success"] is False


# ─────────────────────── jarvis_send_message инструмент ───────────────────────

def test_tool_send_message_send_action(monkeypatch, core):
    monkeypatch.setattr(core.messenger, "send", lambda target, text, subject=None, **k: {"success": True, "target": target})
    out = json.loads(core.tool_jarvis_send_message({"action": "send", "target": "telegram", "text": "hi"}))
    assert out["success"] is True
    assert out["target"] == "telegram"


def test_tool_send_message_list_action(monkeypatch, core):
    monkeypatch.setattr(core.messenger, "list_targets", lambda platform=None: {"success": True, "targets": []})
    out = json.loads(core.tool_jarvis_send_message({"action": "list"}))
    assert out["success"] is True


def test_tool_send_message_unknown_action(core):
    out = json.loads(core.tool_jarvis_send_message({"action": "bogus"}))
    assert out["success"] is False


def test_tool_send_message_send_file_action(monkeypatch, core):
    monkeypatch.setattr(core.messenger, "send_file",
                         lambda target, path, caption=None, **k: {"success": True, "target": target, "file": path})
    out = json.loads(core.tool_jarvis_send_message({"action": "send_file", "target": "telegram",
                                                      "path": "/tmp/photo.png", "caption": "смотри"}))
    assert out["success"] is True
    assert out["file"] == "/tmp/photo.png"


# ─────────────────────── jarvis_voice_note инструмент ──────────────────────

def test_tool_voice_note_success(monkeypatch, core):
    monkeypatch.setattr(core.voice_note, "generate", lambda text, out_dir=None: {"success": True, "path": "/tmp/voice_1.mp3"})
    out = json.loads(core.tool_jarvis_voice_note({"text": "Привет, сэр."}))
    assert out["success"] is True
    assert out["path"] == "/tmp/voice_1.mp3"


def test_tool_voice_note_empty_text(monkeypatch, core):
    monkeypatch.setattr(core.voice_note, "generate", lambda text, out_dir=None: {"success": False, "error": "Пустой текст для голосового сообщения"})
    out = json.loads(core.tool_jarvis_voice_note({"text": ""}))
    assert out["success"] is False


# ─────────────────────── _remote_alert (дублирование в мессенджер) ───────────

def test_remote_alert_noop_without_target(monkeypatch, core):
    sent = []
    monkeypatch.setattr(core.messenger, "is_available", lambda: True)
    monkeypatch.setattr(core.messenger, "send", lambda *a, **k: sent.append(a) or {"success": True})
    core._cfg["remote_alert_target"] = ""
    core._remote_alert("Заголовок", "текст")
    assert sent == []


def test_remote_alert_noop_without_hermes(monkeypatch, core):
    sent = []
    monkeypatch.setattr(core.messenger, "is_available", lambda: False)
    monkeypatch.setattr(core.messenger, "send", lambda *a, **k: sent.append(a) or {"success": True})
    core._cfg["remote_alert_target"] = "telegram"
    core._remote_alert("Заголовок", "текст")
    assert sent == []
    core._cfg["remote_alert_target"] = ""


def test_remote_alert_sends_in_background_thread(monkeypatch, core):
    import threading

    sent = []
    done = threading.Event()

    def fake_send(target, text, subject=None):
        sent.append((target, text, subject))
        done.set()
        return {"success": True}

    monkeypatch.setattr(core.messenger, "is_available", lambda: True)
    monkeypatch.setattr(core.messenger, "send", fake_send)
    core._cfg["remote_alert_target"] = "telegram"
    try:
        core._remote_alert("JARVIS 🔋", "Заряд 15%")
        assert done.wait(timeout=2.0)
        assert sent == [("telegram", "Заряд 15%", "JARVIS 🔋")]
    finally:
        core._cfg["remote_alert_target"] = ""
