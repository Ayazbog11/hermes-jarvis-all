"""HUD-сервер (SSE, события, статика) и merge_config."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from conftest import find_bash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hud"))
import server as hud  # noqa: E402


@pytest.fixture(scope="module")
def hud_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hud.Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def test_index_served(hud_server):
    status, body = _get(hud_server + "/")
    assert status == 200 and b"J.A.R.V.I.S." in body and b"EventSource" in body


def test_status_endpoint(hud_server):
    status, body = _get(hud_server + "/api/status")
    data = json.loads(body)
    assert status == 200 and data["ok"] is True
    assert "hermes" in data  # Hermes не запущен в тестах → up=False, но ключ есть


def test_event_roundtrip_sse(hud_server):
    """POST /api/event → должен прилететь подписчику /events."""
    received = {}

    def listen():
        req = urllib.request.Request(hud_server + "/events")
        with urllib.request.urlopen(req, timeout=5) as r:
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data:") and "tool.start" in line:
                    received["data"] = json.loads(line[5:])
                    break

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)
    body = json.dumps({"event": "tool.start", "data": {"tool": "mac_app", "args": "{}"}}).encode()
    req = urllib.request.Request(hud_server + "/api/event", data=body, headers={"Content-Type": "application/json"})
    assert json.loads(_get_post(req))["ok"]
    t.join(timeout=5)
    assert received["data"]["data"]["tool"] == "mac_app"


def _get_post(req):
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.read()


def test_event_requires_name(hud_server):
    req = urllib.request.Request(hud_server + "/api/event", data=b"{}", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 400


def test_file_endpoint_blocks_outside_roots(hud_server):
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(hud_server + "/file?path=/etc/passwd", timeout=3)
    assert e.value.code == 403


def test_chat_without_hermes_gives_helpful_error(hud_server):
    hud.CONFIG["hermes_url"] = "http://127.0.0.1:1"  # заведомо закрыт
    req = urllib.request.Request(hud_server + "/api/chat", data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode(),
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 502
    assert "hermes gateway" in json.loads(e.value.read())["error"]


def test_hud_client_never_blocks():
    sys.path.insert(0, str(ROOT / "plugins" / "jarvis-core"))
    from hud_client import HudClient

    c = HudClient("http://127.0.0.1:1")
    t0 = time.time()
    for _ in range(50):
        c.emit("x", {})
    assert time.time() - t0 < 0.5  # мгновенно, даже если HUD недоступен


# ─────────────────────────── merge_config ──────────────────────────────────

def test_merge_config_preserves_user_values(tmp_path):
    frag = tmp_path / "frag.yaml"
    tgt = tmp_path / "config.yaml"
    frag.write_text(yaml.safe_dump({
        "plugins": {"enabled": ["jarvis-core", "jarvis-macos"]},
        "tts": {"provider": "edge", "edge": {"voice": "ru-RU-DmitryNeural"}},
        "toolsets": {"hermes-cli": ["web", "jarvis_macos"]},
    }), encoding="utf-8")
    tgt.write_text(yaml.safe_dump({
        "model": "anthropic/claude-sonnet-4",
        "plugins": {"enabled": ["my-plugin"]},
        "tts": {"provider": "elevenlabs"},
        "toolsets": {"hermes-cli": ["terminal", "web"]},
    }), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "merge_config.py"), str(frag), str(tgt)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = yaml.safe_load(tgt.read_text(encoding="utf-8"))
    assert out["model"] == "anthropic/claude-sonnet-4"                 # не тронуто
    assert out["plugins"]["enabled"] == ["my-plugin", "jarvis-core", "jarvis-macos"]  # объединено
    assert out["tts"]["provider"] == "elevenlabs"                       # пользователь победил
    assert out["tts"]["edge"]["voice"] == "ru-RU-DmitryNeural"          # новое добавлено
    assert out["toolsets"]["hermes-cli"] == ["terminal", "web", "jarvis_macos"]


def test_jarvis_config_fragment_is_valid_yaml():
    cfg = yaml.safe_load((ROOT / "config" / "config.jarvis.yaml").read_text(encoding="utf-8"))
    assert set(cfg["plugins"]["enabled"]) == {"jarvis-core", "jarvis-macos", "jarvis-brain"}
    assert cfg["wake_word"]["openwakeword"]["model"] == "hey_jarvis"
    assert cfg["stt"]["provider"] == "local"


def test_shell_scripts_syntax():
    bash = find_bash()
    for script in (ROOT / "install.sh", ROOT / "bin" / "jarvis", ROOT / "scripts" / "setup_cron.sh"):
        r = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"{script}: {r.stderr}"


def test_launchd_plists_are_valid_xml():
    import xml.etree.ElementTree as ET

    for p in (ROOT / "config" / "launchd").glob("*.plist"):
        ET.fromstring(p.read_text(encoding="utf-8"))


def test_post_rejects_cross_origin_and_non_json(hud_server):
    """CSRF-защита: чужая вкладка (Origin ≠ Host) не может слать команды; формы тоже."""
    host = hud_server.split("://", 1)[1]
    body = json.dumps({"event": "x"}).encode()
    # чужой origin
    req = urllib.request.Request(hud_server + "/api/event", data=body,
                                 headers={"Content-Type": "application/json", "Origin": "http://evil.example", "Host": host})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 403
    # свой origin — ок
    req = urllib.request.Request(hud_server + "/api/event", data=body,
                                 headers={"Content-Type": "application/json", "Origin": "http://" + host, "Host": host})
    assert json.loads(urllib.request.urlopen(req, timeout=3).read())["ok"]
    # form-encoded (то, что браузер шлёт без preflight) — отклоняется
    req = urllib.request.Request(hud_server + "/api/event", data=b"event=x",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 415
    # нет CORS-заголовков вообще
    st, _ = _get(hud_server + "/api/status")
    with urllib.request.urlopen(hud_server + "/", timeout=3) as r:
        assert "Access-Control-Allow-Origin" not in r.headers and r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_usage_endpoint_reads_state_db(hud_server, tmp_path, monkeypatch):
    """/api/usage переиспользует scripts/usage_report.py:collect() против настоящего state.db."""
    import sqlite3
    import time as _time

    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY, source TEXT, model TEXT, started_at REAL,
        input_tokens INTEGER, output_tokens INTEGER, estimated_cost_usd REAL)""")
    conn.execute("INSERT INTO sessions VALUES ('s1','cli','claude-x',?,100,50,0.01)", (_time.time(),))
    conn.commit(); conn.close()
    monkeypatch.setattr(hud.usage_report, "STATE_DB", db)
    st, body = _get(hud_server + "/api/usage?since=7")
    data = json.loads(body)
    assert data["ok"] is True
    assert data["total"]["sessions"] == 1
    assert data["total"]["input_tokens"] == 100


def test_usage_endpoint_missing_db_reports_error(hud_server, monkeypatch, tmp_path):
    monkeypatch.setattr(hud.usage_report, "STATE_DB", tmp_path / "does-not-exist.db")
    st, body = _get(hud_server + "/api/usage")
    data = json.loads(body)
    assert data["ok"] is False and "error" in data


def test_metrics_endpoint_prometheus_format(hud_server, tmp_path, monkeypatch):
    """/metrics — Prometheus text exposition format поверх того же state.db, что и /api/usage

    (идея из alex2772/kuni: llm_usage_* по model, см. docs/RESEARCH.md, Раунд 7)."""
    import sqlite3
    import time as _time

    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY, source TEXT, model TEXT, started_at REAL,
        input_tokens INTEGER, output_tokens INTEGER, estimated_cost_usd REAL)""")
    conn.execute("INSERT INTO sessions VALUES ('s1','cli','claude-x',?,100,50,0.01)", (_time.time(),))
    conn.commit(); conn.close()
    monkeypatch.setattr(hud.usage_report, "STATE_DB", db)
    st, body = _get(hud_server + "/metrics")
    text = body.decode("utf-8")
    assert st == 200
    assert "jarvis_llm_usage_input_tokens_total" in text
    assert 'model="claude-x"} 100' in text
    assert 'jarvis_llm_usage_output_tokens_total{model="claude-x"} 50' in text


def test_metrics_endpoint_missing_db_stays_valid_text(hud_server, monkeypatch, tmp_path):
    monkeypatch.setattr(hud.usage_report, "STATE_DB", tmp_path / "does-not-exist.db")
    st, body = _get(hud_server + "/metrics")
    assert st == 200
    assert body.decode("utf-8").startswith("#")


def test_send_endpoint_requires_target_and_text(hud_server):
    req = urllib.request.Request(hud_server + "/api/send", data=json.dumps({"target": "", "text": ""}).encode(),
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 400


def test_send_endpoint_calls_messenger(hud_server, monkeypatch):
    calls = []
    monkeypatch.setattr(hud.messenger, "send", lambda target, text, subject=None: calls.append((target, text, subject)) or {"success": True})
    req = urllib.request.Request(hud_server + "/api/send",
                                 data=json.dumps({"target": "telegram", "text": "hi"}).encode(),
                                 headers={"Content-Type": "application/json"})
    body = urllib.request.urlopen(req, timeout=3).read()
    assert json.loads(body)["success"] is True
    assert calls == [("telegram", "hi", None)]


def test_send_targets_endpoint(hud_server, monkeypatch):
    monkeypatch.setattr(hud.messenger, "list_targets", lambda platform=None: {"success": True, "targets": [{"platform": "telegram"}]})
    st, body = _get(hud_server + "/api/send/targets")
    data = json.loads(body)
    assert data["success"] is True and data["targets"][0]["platform"] == "telegram"


def test_send_voice_endpoint_requires_target_and_text(hud_server):
    req = urllib.request.Request(hud_server + "/api/send/voice", data=json.dumps({"target": "", "text": ""}).encode(),
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=3)
    assert e.value.code == 400


def test_send_voice_endpoint_generates_and_sends(hud_server, monkeypatch):
    monkeypatch.setattr(hud.voice_note, "generate", lambda text, out_dir=None: {"success": True, "path": "/tmp/voice_1.mp3", "mime": "audio/mpeg"})
    calls = []
    monkeypatch.setattr(hud.messenger, "send_file",
                         lambda target, path, caption=None: calls.append((target, path, caption)) or {"success": True})
    req = urllib.request.Request(hud_server + "/api/send/voice",
                                 data=json.dumps({"target": "telegram", "text": "Привет"}).encode(),
                                 headers={"Content-Type": "application/json"})
    body = urllib.request.urlopen(req, timeout=3).read()
    assert json.loads(body)["success"] is True
    assert calls == [("telegram", "/tmp/voice_1.mp3", None)]


def test_send_voice_endpoint_propagates_generation_failure(hud_server, monkeypatch):
    monkeypatch.setattr(hud.voice_note, "generate", lambda text, out_dir=None: {"success": False, "error": "нет движка TTS"})
    req = urllib.request.Request(hud_server + "/api/send/voice",
                                 data=json.dumps({"target": "telegram", "text": "Привет"}).encode(),
                                 headers={"Content-Type": "application/json"})
    body = urllib.request.urlopen(req, timeout=3).read()
    data = json.loads(body)
    assert data["success"] is False and "TTS" in data["error"]


def test_model_get_endpoint(hud_server, monkeypatch):
    monkeypatch.setattr(hud.model_switch, "get_all", lambda: {"success": True, "values": {"chat_model": "x"}, "fields": {}})
    st, body = _get(hud_server + "/api/model")
    data = json.loads(body)
    assert data["success"] is True and data["values"]["chat_model"] == "x"


def test_model_set_endpoint(hud_server, monkeypatch):
    calls = []
    monkeypatch.setattr(hud.model_switch, "set_value", lambda field, value: calls.append((field, value)) or {"success": True})
    req = urllib.request.Request(hud_server + "/api/model",
                                 data=json.dumps({"field": "chat_model", "value": "openai/gpt-4o"}).encode(),
                                 headers={"Content-Type": "application/json"})
    body = urllib.request.urlopen(req, timeout=3).read()
    assert json.loads(body)["success"] is True
    assert calls == [("chat_model", "openai/gpt-4o")]


def test_model_profiles_get_endpoint(hud_server, monkeypatch):
    monkeypatch.setattr(hud.model_switch, "list_profiles",
                        lambda: {"success": True, "profiles": {"openrouter": {"model.provider": "openrouter"}}, "fields": {}})
    st, body = _get(hud_server + "/api/model/profiles")
    data = json.loads(body)
    assert st == 200 and data["success"] is True and "openrouter" in data["profiles"]


def test_model_profiles_save_endpoint(hud_server, monkeypatch):
    calls = []
    monkeypatch.setattr(hud.model_switch, "save_profile",
                        lambda name, fields: calls.append((name, fields)) or {"success": True, "name": name})
    req = urllib.request.Request(hud_server + "/api/model/profiles",
                                 data=json.dumps({"name": "local-ollama", "fields": {"model.provider": "custom"}}).encode(),
                                 headers={"Content-Type": "application/json"})
    body = urllib.request.urlopen(req, timeout=3).read()
    assert json.loads(body)["success"] is True
    assert calls == [("local-ollama", {"model.provider": "custom"})]


def test_model_profiles_apply_endpoint(hud_server, monkeypatch):
    monkeypatch.setattr(hud.model_switch, "apply_profile", lambda name: {"success": True, "name": name, "results": {}})
    req = urllib.request.Request(hud_server + "/api/model/profiles/apply",
                                 data=json.dumps({"name": "local-ollama"}).encode(),
                                 headers={"Content-Type": "application/json"})
    body = urllib.request.urlopen(req, timeout=3).read()
    assert json.loads(body)["success"] is True


def test_model_profiles_delete_endpoint(hud_server, monkeypatch):
    monkeypatch.setattr(hud.model_switch, "delete_profile", lambda name: {"success": True})
    req = urllib.request.Request(hud_server + "/api/model/profiles/delete",
                                 data=json.dumps({"name": "local-ollama"}).encode(),
                                 headers={"Content-Type": "application/json"})
    body = urllib.request.urlopen(req, timeout=3).read()
    assert json.loads(body)["success"] is True


def test_telegram_status_endpoint_not_configured(hud_server, monkeypatch):
    monkeypatch.setattr(hud.telegram_userbot, "status", lambda: {"available": True, "configured": False, "authorized": False})
    st, body = _get(hud_server + "/api/telegram/status")
    data = json.loads(body)
    assert st == 200 and data["configured"] is False


def test_telegram_status_endpoint_authorized_includes_unread(hud_server, monkeypatch):
    monkeypatch.setattr(hud.telegram_userbot, "status", lambda: {"available": True, "configured": True, "authorized": True, "username": "sir"})
    monkeypatch.setattr(hud.telegram_userbot, "unread_summary", lambda: {"success": True, "total_unread": 7, "chats_with_unread": 3})
    st, body = _get(hud_server + "/api/telegram/status")
    data = json.loads(body)
    assert st == 200 and data["authorized"] is True
    assert data["total_unread"] == 7 and data["chats_with_unread"] == 3


def test_brain_overview_endpoint(hud_server, tmp_path, monkeypatch):
    """/api/brain читает базу знаний в режиме read-only."""
    sys.path.insert(0, str(ROOT / "plugins" / "jarvis-brain"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("brain_db", ROOT / "plugins" / "jarvis-brain" / "db.py")
    db = importlib.util.module_from_spec(spec); spec.loader.exec_module(db)
    b = db.Brain(tmp_path / "brain.db")
    b.remember("Пользователь любит зелёный чай", kind="preference", entity="Чай")
    b.save_episode("2026-09-08", "Пили чай.", "")
    b.close()
    monkeypatch.setitem(hud.CONFIG, "brain_db", str(tmp_path / "brain.db"))
    from urllib.parse import quote
    st, body = _get(hud_server + "/api/brain?q=" + quote("чай"))
    data = json.loads(body)
    assert data["ok"] and data["notes"] == 1 and data["entities"] == 1 and data["episodes"] == 1
    assert data["search"][0]["entity"] == "Чай" and data["kinds"][0]["kind"] == "preference"
    monkeypatch.setitem(hud.CONFIG, "brain_db", str(tmp_path / "nope.db"))
    assert json.loads(_get(hud_server + "/api/brain")[1])["ok"] is False
