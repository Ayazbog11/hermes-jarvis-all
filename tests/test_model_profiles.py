"""Тесты профилей провайдеров в scripts/model_switch.py (Round 12) — без реального `hermes`.

Профили — способ сохранить набор из provider/model/ключа под именем и применить одной
кнопкой в HUD (см. docs/AI-MODELS.md). Файл с профилями изолирован через HERMES_HOME (tmp_path),
чтобы тесты не трогали реальный ~/.hermes пользователя.
"""

from __future__ import annotations

import importlib.util
import json


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("jarvis_model_switch_profiles", "scripts/model_switch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_list_profiles_empty_by_default(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    result = m.list_profiles()
    assert result["success"] is True
    assert result["profiles"] == {}


def test_save_profile_persists(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    result = m.save_profile("openrouter", {"model.provider": "openrouter", "model.default": "openrouter/auto",
                                            "OPENROUTER_API_KEY": "sk-or-secretsecret1234"})
    assert result["success"] is True
    data = json.loads(m._profiles_path().read_text(encoding="utf-8"))
    assert data["openrouter"]["OPENROUTER_API_KEY"] == "sk-or-secretsecret1234"


def test_save_profile_requires_name(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    result = m.save_profile("", {"model.provider": "openrouter"})
    assert result["success"] is False


def test_save_profile_ignores_disallowed_keys(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    m.save_profile("p1", {"model.provider": "openrouter", "SOME_RANDOM_KEY": "x"})
    data = json.loads(m._profiles_path().read_text(encoding="utf-8"))
    assert "SOME_RANDOM_KEY" not in data["p1"]
    assert data["p1"] == {"model.provider": "openrouter"}


def test_save_profile_rejects_empty_fields(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    result = m.save_profile("p1", {"model.provider": "   "})
    assert result["success"] is False


def test_list_profiles_masks_secret_keys(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    m.save_profile("openrouter", {"OPENROUTER_API_KEY": "sk-or-secretsecret1234"})
    result = m.list_profiles()
    shown = result["profiles"]["openrouter"]["OPENROUTER_API_KEY"]
    assert shown != "sk-or-secretsecret1234"
    assert shown.endswith("1234")


def test_list_profiles_does_not_mask_non_secret_keys(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    m.save_profile("openrouter", {"model.provider": "openrouter"})
    result = m.list_profiles()
    assert result["profiles"]["openrouter"]["model.provider"] == "openrouter"


def test_delete_profile_removes_it(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    m.save_profile("p1", {"model.provider": "openrouter"})
    result = m.delete_profile("p1")
    assert result["success"] is True
    assert m.list_profiles()["profiles"] == {}


def test_delete_profile_not_found(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    result = m.delete_profile("does-not-exist")
    assert result["success"] is False


def test_apply_profile_not_found(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    result = m.apply_profile("does-not-exist")
    assert result["success"] is False


def test_apply_profile_no_hermes_binary(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    m.save_profile("p1", {"model.provider": "openrouter"})
    monkeypatch.setattr(m, "_hermes_bin", lambda: None)
    result = m.apply_profile("p1")
    assert result["success"] is False
    assert "hermes" in result["error"]


def test_apply_profile_runs_config_set_per_key(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    m.save_profile("p1", {"model.provider": "openrouter", "model.default": "openrouter/auto"})
    monkeypatch.setattr(m, "_hermes_bin", lambda: "hermes")
    calls = []

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeResult()

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    result = m.apply_profile("p1")
    assert result["success"] is True
    assert len(calls) == 2
    assert all(c[:3] == ["hermes", "config", "set"] for c in calls)


def test_apply_profile_reports_partial_failure(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    m.save_profile("p1", {"model.provider": "openrouter", "model.default": "openrouter/auto"})
    monkeypatch.setattr(m, "_hermes_bin", lambda: "hermes")

    class FakeResultOk:
        returncode = 0
        stdout = ""
        stderr = ""

    class FakeResultFail:
        returncode = 1
        stdout = ""
        stderr = "boom"

    def fake_run(cmd, **kwargs):
        return FakeResultOk() if cmd[3] == "model.provider" else FakeResultFail()

    monkeypatch.setattr(m.subprocess, "run", fake_run)
    result = m.apply_profile("p1")
    assert result["success"] is False
    assert result["results"]["model.provider"]["success"] is True
    assert result["results"]["model.default"]["success"] is False


def test_hermes_bin_falls_back_to_hermes_agent_bin_when_path_stale(monkeypatch, tmp_path):
    """shutil.which() может не находить `hermes`, даже если он реально установлен: PATH,
    унаследованный HUD-процессом (Scheduled Task при логине), может быть записан ДО того,
    как install.ps1 дописал в него bin-каталог Hermes, либо самообновление Hermes через
    Desktop UI удалило hermes-agent/bin, не тронув PATH (см. апстрим NousResearch/hermes-agent
    #91563). `_hermes_bin()` должен в этом случае проверить типовые install-пути напрямую
    под $HERMES_HOME, а не молча сдаться.
    """
    m = load(monkeypatch, tmp_path)
    monkeypatch.setattr(m.shutil, "which", lambda name: None)
    bin_dir = tmp_path / "hermes-agent" / "bin"
    bin_dir.mkdir(parents=True)
    exe_name = "hermes.exe" if m.os.name == "nt" else "hermes"
    fake_hermes = bin_dir / exe_name
    fake_hermes.write_text("fake")
    assert m._hermes_bin() == str(fake_hermes)


def test_hermes_bin_returns_none_when_nothing_found(monkeypatch, tmp_path):
    m = load(monkeypatch, tmp_path)
    monkeypatch.setattr(m.shutil, "which", lambda name: None)
    assert m._hermes_bin() is None
