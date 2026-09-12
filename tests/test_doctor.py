"""jarvis doctor: не падает без Hermes, JSON-контракт, автопочинка .env."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("jarvis_doctor", ROOT / "scripts" / "doctor.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_doctor"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_no_hermes_is_single_fail(monkeypatch, tmp_path, capsys):
    d = load(monkeypatch, tmp_path)
    monkeypatch.setattr(d.shutil, "which", lambda *_: None)
    monkeypatch.setattr(d, "BIN", tmp_path / "nobin")
    assert d.main(["--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["checks"][0]["status"] == "fail" and "install.sh" in out["checks"][0]["fix"]


def test_env_fix_writes_keys(monkeypatch, tmp_path):
    d = load(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=x\n", encoding="utf-8")
    c = d.check_env_api(fix=False)
    assert c.status == "fail" and "API_SERVER_KEY" in c.note
    c = d.check_env_api(fix=True)
    assert c.fixed
    env = d.read_env()
    assert env["API_SERVER_ENABLED"] == "true" and len(env["API_SERVER_KEY"]) >= 32 and env["OPENROUTER_API_KEY"] == "x"
    assert d.check_env_api(fix=False).status == "ok"


def test_version_check_reads_update_json(monkeypatch, tmp_path):
    d = load(monkeypatch, tmp_path)
    (tmp_path / "jarvis").mkdir()
    (tmp_path / "jarvis" / "install.json").write_text(json.dumps({"version": "1.8.0", "channel": "stable"}), encoding="utf-8")
    assert d.check_version(False).status == "ok"
    (tmp_path / "jarvis" / "update.json").write_text(json.dumps({"available": True, "latest": "1.9.0"}), encoding="utf-8")
    c = d.check_version(False)
    assert c.status == "warn" and "1.9.0" in c.note and c.fix_hint == "jarvis update"


def test_check_telegram_ok_when_telethon_importable(monkeypatch, tmp_path):
    d = load(monkeypatch, tmp_path)
    c = d.check_telegram(fix=False)
    # telethon подтягивается в этой песочнице для тестового прогона — проверяем, что доктор
    # видит его через тот же sys.executable, что использует pytest сейчас (тот же интерпретатор,
    # что и у HUD/setup_scheduled_tasks.py в реальной установке).
    assert c.status == "ok"
    assert "telethon" in c.note


def test_check_telegram_warns_when_not_importable(monkeypatch, tmp_path):
    d = load(monkeypatch, tmp_path)
    # Симулируем интерпретатор без telethon: используем -S (skip site) не годится (модуль всё
    # равно виден через обычные site-packages) — вместо этого подменяем sh() так, будто импорт
    # правда падает, точно так же, как это выглядело бы на другом (venv-рассинхронизированном)
    # интерпретаторе.
    monkeypatch.setattr(d, "sh", lambda cmd, timeout=20, env=None: (1, "ModuleNotFoundError: No module named 'telethon'"))
    c = d.check_telegram(fix=False)
    assert c.status == "warn"
    assert "не импортируется" in c.note


def test_check_model_treats_not_found_marker_as_unset(monkeypatch, tmp_path):
    d = load(monkeypatch, tmp_path)
    # Regression guard: some CLI builds могут вывести текстовое "not found"/"not set" вместо
    # пустой строки для незаданного ключа — доктор не должен показывать это как имя модели.
    monkeypatch.setattr(d, "sh", lambda cmd, timeout=20, env=None: (0, "not found"))
    c = d.check_model(fix=False, do_ping=False)
    assert c.status == "fail"
    assert "не настроена" in c.note
