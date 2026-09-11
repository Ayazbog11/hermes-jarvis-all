"""Тесты scripts/ollama_local.py — без реальной сети/подпроцессов Ollama/hermes."""

from __future__ import annotations

import importlib.util
import subprocess



def load(monkeypatch):
    spec = importlib.util.spec_from_file_location("jarvis_ollama_local", "scripts/ollama_local.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_is_running_false_when_unreachable(monkeypatch):
    m = load(monkeypatch)

    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(m.urllib.request, "urlopen", boom)
    assert m.is_running() is False


def test_list_models_returns_parsed_json(monkeypatch):
    m = load(monkeypatch)

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"models": [{"name": "qwen3:8b", "size": 4000000000}]}'

    monkeypatch.setattr(m.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    models = m.list_models()
    assert models == [{"name": "qwen3:8b", "size": 4000000000}]


def test_list_models_empty_on_error(monkeypatch):
    m = load(monkeypatch)

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(m.urllib.request, "urlopen", boom)
    assert m.list_models() == []


def test_ollama_installed_reflects_which(monkeypatch):
    m = load(monkeypatch)
    monkeypatch.setattr(m.shutil, "which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    assert m.ollama_installed() is True
    monkeypatch.setattr(m.shutil, "which", lambda name: None)
    assert m.ollama_installed() is False


def test_cmd_status_reports_missing_ollama(monkeypatch, capsys):
    m = load(monkeypatch)
    monkeypatch.setattr(m, "ollama_installed", lambda: False)
    rc = m.cmd_status(None)
    assert rc == 1
    assert "не найден" in capsys.readouterr().out


def test_hermes_config_set_success(monkeypatch):
    m = load(monkeypatch)

    def fake_run(args, **kwargs):
        assert args[:2] == ["hermes", "config"]
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    assert m.hermes_config_set("model.default", "qwen3:8b") is True


def test_hermes_config_set_failure_returns_false(monkeypatch):
    m = load(monkeypatch)

    def fake_run(args, **kwargs):
        raise FileNotFoundError("hermes not found")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    assert m.hermes_config_set("model.default", "qwen3:8b") is False


def test_hermes_config_get_returns_empty_on_error(monkeypatch):
    m = load(monkeypatch)

    def fake_run(args, **kwargs):
        raise FileNotFoundError("hermes not found")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    assert m.hermes_config_get("model.default") == ""


def test_cmd_use_fails_when_ollama_not_running(monkeypatch, capsys):
    m = load(monkeypatch)
    monkeypatch.setattr(m, "is_running", lambda: False)
    import argparse

    args = argparse.Namespace(model="qwen3:8b", context=0, vision=False, skip_check=False, no_verify=False)
    rc = m.cmd_use(args)
    assert rc == 1
    assert "не запущен" in capsys.readouterr().err


def test_cmd_use_sets_vision_config(monkeypatch):
    """vision-модели не проверяются текстовым пингом (--no-verify неявно), поэтому cmd_use не должен звать hermes chat."""
    m = load(monkeypatch)
    monkeypatch.setattr(m, "is_running", lambda: True)
    monkeypatch.setattr(m, "list_models", lambda: [{"name": "qwen2.5vl:7b"}])
    calls = []
    monkeypatch.setattr(m, "hermes_config_set", lambda k, v: calls.append((k, v)) or True)
    monkeypatch.setattr(m, "hermes_config_get", lambda k: "")
    monkeypatch.setattr(m, "ping_model", lambda: (_ for _ in ()).throw(AssertionError("не должен звать ping для --vision")))
    import argparse

    args = argparse.Namespace(model="qwen2.5vl:7b", context=0, vision=True, skip_check=False, no_verify=False)
    rc = m.cmd_use(args)
    assert rc == 0
    keys = [k for k, _ in calls]
    assert "auxiliary.vision.model" in keys
    assert "auxiliary.vision.base_url" in keys


def test_cmd_use_sets_main_model_config_and_verifies(monkeypatch):
    m = load(monkeypatch)
    monkeypatch.setattr(m, "is_running", lambda: True)
    monkeypatch.setattr(m, "list_models", lambda: [{"name": "qwen3:8b"}])
    calls = []
    monkeypatch.setattr(m, "hermes_config_set", lambda k, v: calls.append((k, v)) or True)
    monkeypatch.setattr(m, "hermes_config_get", lambda k: "")
    monkeypatch.setattr(m, "ping_model", lambda: (True, "ok"))
    import argparse

    args = argparse.Namespace(model="qwen3:8b", context=32768, vision=False, skip_check=False, no_verify=False)
    rc = m.cmd_use(args)
    assert rc == 0
    keys = [k for k, _ in calls]
    assert "model.provider" in keys
    assert "model.base_url" in keys
    assert "model.default" in keys
    assert "model.context_length" in keys


def test_cmd_use_rolls_back_when_model_unhealthy(monkeypatch, capsys):
    """Ключевой сценарий безопасности (Раунд 7, паттерн model-watchdog): если новая модель не отвечает,
    конфигурация должна вернуться на прежние (снятые ДО изменения) значения, а команда — вернуть код 1."""
    m = load(monkeypatch)
    monkeypatch.setattr(m, "is_running", lambda: True)
    monkeypatch.setattr(m, "list_models", lambda: [{"name": "qwen3:8b"}])
    old_values = {"model.provider": "anthropic", "model.base_url": "", "model.default": "claude-3-5-sonnet"}
    monkeypatch.setattr(m, "hermes_config_get", lambda k: old_values.get(k, ""))
    set_calls = []
    monkeypatch.setattr(m, "hermes_config_set", lambda k, v: set_calls.append((k, v)) or True)
    monkeypatch.setattr(m, "ping_model", lambda: (False, "HTTP 500"))
    import argparse

    args = argparse.Namespace(model="qwen3:8b", context=0, vision=False, skip_check=False, no_verify=False)
    rc = m.cmd_use(args)
    assert rc == 1
    err = capsys.readouterr().err
    assert "откатываю" in err.lower()
    # два прохода: сначала запись новых значений, потом откат на старые — старые значения должны
    # присутствовать среди set-вызовов ПОСЛЕ новых
    new_idx = set_calls.index(("model.default", "qwen3:8b"))
    rollback_idx = set_calls.index(("model.provider", "anthropic"))
    assert rollback_idx > new_idx
    assert ("model.default", "claude-3-5-sonnet") in set_calls[new_idx + 1:]


def test_cmd_use_skips_verify_with_no_verify_flag(monkeypatch):
    m = load(monkeypatch)
    monkeypatch.setattr(m, "is_running", lambda: True)
    monkeypatch.setattr(m, "list_models", lambda: [{"name": "qwen3:8b"}])
    monkeypatch.setattr(m, "hermes_config_set", lambda k, v: True)
    monkeypatch.setattr(m, "hermes_config_get", lambda k: "")
    monkeypatch.setattr(m, "ping_model", lambda: (_ for _ in ()).throw(AssertionError("не должен звать ping")))
    import argparse

    args = argparse.Namespace(model="qwen3:8b", context=0, vision=False, skip_check=False, no_verify=True)
    rc = m.cmd_use(args)
    assert rc == 0


def test_ping_model_detects_error_response(monkeypatch):
    m = load(monkeypatch)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="Error code: 500 - internal error", stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    ok, detail = m.ping_model()
    assert ok is False


def test_ping_model_detects_healthy_response(monkeypatch):
    m = load(monkeypatch)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    ok, detail = m.ping_model()
    assert ok is True and detail == "ok"


def test_cmd_recommend_prints_models(capsys, monkeypatch):
    m = load(monkeypatch)
    rc = m.cmd_recommend(None)
    assert rc == 0
    out = capsys.readouterr().out
    for name, _ in m.RECOMMENDED:
        assert name in out
