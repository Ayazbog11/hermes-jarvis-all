"""Регистрация плагина jarvis-windows, валидность схем, поведение обработчиков вне Windows.

Зеркало test_plugins.py (jarvis-macos), адаптировано под win_* инструменты.
"""

from __future__ import annotations

import json
import platform

import pytest
import yaml

from conftest import PLUGINS, load_plugin

IS_WINDOWS = platform.system() == "Windows"


# ─────────────────────────── манифест и схемы ───────────────────────────────

def test_manifest_valid():
    m = yaml.safe_load((PLUGINS / "jarvis-windows" / "plugin.yaml").read_text(encoding="utf-8"))
    assert m["name"] == "jarvis-windows"
    assert "version" in m and "description" in m
    assert isinstance(m.get("provides_tools", []), list)


def test_manifest_lists_all_tools():
    win = load_plugin("jarvis-windows")
    m = yaml.safe_load((PLUGINS / "jarvis-windows" / "plugin.yaml").read_text(encoding="utf-8"))
    declared = set(m["provides_tools"])
    actual = {s["name"] for s in win.schemas.ALL_SCHEMAS}
    assert declared == actual, f"manifest≠schemas: {declared ^ actual}"
    assert actual == set(win.tools.HANDLERS), "у каждой схемы должен быть обработчик"


def _check_schema(schema: dict):
    assert schema["name"].isidentifier()
    assert len(schema["description"]) > 20
    params = schema["parameters"]
    assert params["type"] == "object"
    for req in params.get("required", []):
        assert req in params["properties"], f"{schema['name']}: required {req} без описания"
    for pname, p in params["properties"].items():
        assert "type" in p, f"{schema['name']}.{pname}: нет type"


def test_all_schemas_well_formed():
    win = load_plugin("jarvis-windows")
    for s in win.schemas.ALL_SCHEMAS:
        _check_schema(s)


# ─────────────────────────── регистрация ────────────────────────────────────

def test_windows_register(ctx):
    win = load_plugin("jarvis-windows")
    win.register(ctx)
    assert len(ctx.tools) == len(win.schemas.ALL_SCHEMAS)
    assert all(t["toolset"] == "jarvis_windows" for t in ctx.tools.values())
    assert {"screen", "vol", "sysinfo", "lock"} <= set(ctx.commands)


# ─────────────────────────── обработчики ────────────────────────────────────

def test_handlers_always_return_json():
    """Любой обработчик на любой платформе возвращает валидный JSON и не бросает."""
    win = load_plugin("jarvis-windows")
    for name, handler in win.tools.HANDLERS.items():
        out = handler({}, task_id="t")  # намеренно пустые аргументы
        data = json.loads(out)
        assert "success" in data, name
        if not IS_WINDOWS:
            assert data["success"] is False and "Windows" in data["error"], name


def test_power_requires_confirmation():
    win = load_plugin("jarvis-windows")
    if not IS_WINDOWS:
        pytest.skip("Windows only")
    out = json.loads(win.tools.win_power({"action": "shutdown"}))
    assert out["success"] is False and "подтвержд" in out["error"]


def test_powershell_disabled_by_default():
    win = load_plugin("jarvis-windows")
    if not IS_WINDOWS:
        pytest.skip("Windows only")
    out = json.loads(win.tools.win_powershell({"script": "1"}))
    assert out["success"] is False and "allow_raw_powershell" in out["error"]


def test_resolve_target():
    win = load_plugin("jarvis-windows")
    r = win.win.resolve_target
    assert r("youtube.com") == "https://youtube.com"
    assert r("https://a.b/c") == "https://a.b/c"
    assert r("Загрузки").replace("\\", "/").endswith("/Downloads")
    resolved = r("~/x.txt").replace("\\", "/")
    assert resolved.endswith("/x.txt") and not resolved.startswith("~")


def test_as_ps_escapes():
    win = load_plugin("jarvis-windows")
    assert win.win.as_ps("a'b") == "'a''b'"
    assert win.win.as_ps("plain") == "'plain'"


def test_type_rejects_unknown_modifiers():
    """Модификаторы клавиш собираются в строку SendKeys → строгий allow-list, иначе инъекция."""
    win = load_plugin("jarvis-windows")
    if not IS_WINDOWS:
        pytest.skip("Windows only")
    out = json.loads(win.tools.win_type({"action": "keystroke", "text": "a", "modifiers": ["cmd_evil"]}))
    assert out["success"] is False and "модификатор" in out["error"]


def test_windows_manifest_declares_no_macos_plugin_dependency():
    core_manifest = yaml.safe_load((PLUGINS / "jarvis-core" / "plugin.yaml").read_text(encoding="utf-8"))
    requires = core_manifest.get("requires_plugins", [])
    assert "jarvis-macos" not in requires and "jarvis-windows" not in requires


def test_file_manage_safe_ops_platform_independent(tmp_path, monkeypatch):
    """Логика путей (rename/move/mkdir/list) не зависит от ОС — можно проверить где угодно."""
    win = load_plugin("jarvis-windows")
    monkeypatch.setattr(win.tools.win, "IS_WINDOWS", True)
    monkeypatch.setattr(win.win, "IS_WINDOWS", True)
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    out = json.loads(win.tools.win_file_manage({"action": "rename", "path": str(f), "new_name": "b.txt"}))
    assert out["success"] and (tmp_path / "b.txt").exists()
    out = json.loads(win.tools.win_file_manage({"action": "mkdir", "path": str(tmp_path / "sub")}))
    assert out["success"] and (tmp_path / "sub").is_dir()
    out = json.loads(win.tools.win_file_manage({"action": "move", "path": str(tmp_path / "b.txt"), "destination": str(tmp_path / "sub")}))
    assert out["success"] and (tmp_path / "sub" / "b.txt").exists()
    out = json.loads(win.tools.win_file_manage({"action": "list", "path": str(tmp_path)}))
    assert out["success"] and out["items"][0]["name"] == "sub"
    out = json.loads(win.tools.win_file_manage({"action": "trash", "path": str(tmp_path / "nope")}))
    assert out["success"] is False


def test_selftest_classifier_windows_branch(monkeypatch):
    """selftest.py — общий скрипт для macOS/Windows; здесь форсируем ветку Windows,
    т.к. тесты гоняются на Linux/macOS CI и IS_WINDOWS там всегда False."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("winselftest", "scripts/selftest.py")
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    monkeypatch.setattr(st, "IS_WINDOWS", True)
    assert st.classify({"success": True}) == ("ok", "")
    s, note = st.classify({"success": False, "error": "Access is denied"})
    assert s == "perm" and "администратора" in note
    s, note = st.classify({"success": False, "error": "Windows не предоставляет надёжный публичный способ (unsupported)"})
    assert s == "unsupported"
    assert st.classify({"success": False, "error": "что-то странное"})[0] == "fail"
    assert all(h in load_plugin("jarvis-windows").tools.HANDLERS for h, _, _ in st.CHECKS_WIN)


def test_selftest_checks_win_reference_real_handlers():
    import importlib.util
    spec = importlib.util.spec_from_file_location("selftest_win_candidates", "scripts/selftest.py")
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    assert all(h in load_plugin("jarvis-windows").tools.HANDLERS for h, _, _ in st.CHECKS_WIN)
