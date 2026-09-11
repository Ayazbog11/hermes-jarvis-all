"""Регистрация плагина jarvis-linux, валидность схем, поведение обработчиков вне Linux.

Зеркало test_plugins_windows.py (jarvis-windows), адаптировано под linux_* инструменты.
"""

from __future__ import annotations

import json
import platform

import pytest
import yaml

from conftest import PLUGINS, load_plugin

IS_LINUX = platform.system() == "Linux"


# ─────────────────────────── манифест и схемы ───────────────────────────────

def test_manifest_valid():
    m = yaml.safe_load((PLUGINS / "jarvis-linux" / "plugin.yaml").read_text(encoding="utf-8"))
    assert m["name"] == "jarvis-linux"
    assert "version" in m and "description" in m
    assert isinstance(m.get("provides_tools", []), list)


def test_manifest_lists_all_tools():
    lin = load_plugin("jarvis-linux")
    m = yaml.safe_load((PLUGINS / "jarvis-linux" / "plugin.yaml").read_text(encoding="utf-8"))
    declared = set(m["provides_tools"])
    actual = {s["name"] for s in lin.schemas.ALL_SCHEMAS}
    assert declared == actual, f"manifest≠schemas: {declared ^ actual}"
    assert actual == set(lin.tools.HANDLERS), "у каждой схемы должен быть обработчик"


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
    lin = load_plugin("jarvis-linux")
    for s in lin.schemas.ALL_SCHEMAS:
        _check_schema(s)


# ─────────────────────────── регистрация ────────────────────────────────────

def test_linux_register(ctx):
    lin = load_plugin("jarvis-linux")
    lin.register(ctx)
    assert len(ctx.tools) == len(lin.schemas.ALL_SCHEMAS)
    assert all(t["toolset"] == "jarvis_linux" for t in ctx.tools.values())
    assert {"screen", "vol", "sysinfo", "lock"} <= set(ctx.commands)


# ─────────────────────────── обработчики ────────────────────────────────────

def test_handlers_always_return_json():
    """Любой обработчик на любой платформе возвращает валидный JSON и не бросает."""
    lin = load_plugin("jarvis-linux")
    for name, handler in lin.tools.HANDLERS.items():
        out = handler({}, task_id="t")  # намеренно пустые аргументы
        data = json.loads(out)
        assert "success" in data, name
        if not IS_LINUX:
            assert data["success"] is False and "Linux" in data["error"], name


def test_power_requires_confirmation():
    lin = load_plugin("jarvis-linux")
    if not IS_LINUX:
        pytest.skip("Linux only")
    out = json.loads(lin.tools.linux_power({"action": "shutdown"}))
    assert out["success"] is False and "подтвержд" in out["error"]


def test_shell_disabled_by_default():
    lin = load_plugin("jarvis-linux")
    if not IS_LINUX:
        pytest.skip("Linux only")
    out = json.loads(lin.tools.linux_shell({"script": "echo 1"}))
    assert out["success"] is False and "allow_raw_shell" in out["error"]


def test_resolve_target():
    lin = load_plugin("jarvis-linux")
    r = lin.linux.resolve_target
    assert r("youtube.com") == "https://youtube.com"
    assert r("https://a.b/c") == "https://a.b/c"
    assert r("Загрузки").replace("\\", "/").endswith("/Downloads")
    resolved = r("~/x.txt").replace("\\", "/")
    assert resolved.endswith("/x.txt") and not resolved.startswith("~")


def test_type_requires_backend():
    """Без xdotool/ydotool в PATH — или без доступа к X-дисплею (headless/SSH) — type_text должен
    явно сообщить о причине, а не упасть молча / с непонятным сырым выводом xdotool."""
    lin = load_plugin("jarvis-linux")
    if not IS_LINUX:
        pytest.skip("Linux only")
    out = json.loads(lin.tools.linux_type({"action": "type_text", "text": "hi"}))
    if not out["success"]:
        assert "xdotool" in out["error"] or "ydotool" in out["error"] or "DISPLAY" in out["error"]


def test_keystroke_rejects_unknown_modifiers():
    lin = load_plugin("jarvis-linux")
    if not IS_LINUX:
        pytest.skip("Linux only")
    out = json.loads(lin.tools.linux_type({"action": "keystroke", "text": "a", "modifiers": ["cmd_evil"]}))
    assert out["success"] is False and "модификатор" in out["error"]


def test_linux_manifest_declares_no_other_os_plugin_dependency():
    core_manifest = yaml.safe_load((PLUGINS / "jarvis-core" / "plugin.yaml").read_text(encoding="utf-8"))
    requires = core_manifest.get("requires_plugins", [])
    assert "jarvis-macos" not in requires and "jarvis-windows" not in requires and "jarvis-linux" not in requires


def test_file_manage_safe_ops_platform_independent(tmp_path, monkeypatch):
    """Логика путей (rename/move/mkdir/list) не зависит от ОС — можно проверить где угодно."""
    lin = load_plugin("jarvis-linux")
    monkeypatch.setattr(lin.tools.lx, "IS_LINUX", True)
    monkeypatch.setattr(lin.linux, "IS_LINUX", True)
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    out = json.loads(lin.tools.linux_file_manage({"action": "rename", "path": str(f), "new_name": "b.txt"}))
    assert out["success"] and (tmp_path / "b.txt").exists()
    out = json.loads(lin.tools.linux_file_manage({"action": "mkdir", "path": str(tmp_path / "sub")}))
    assert out["success"] and (tmp_path / "sub").is_dir()
    out = json.loads(lin.tools.linux_file_manage({"action": "move", "path": str(tmp_path / "b.txt"), "destination": str(tmp_path / "sub")}))
    assert out["success"] and (tmp_path / "sub" / "b.txt").exists()
    out = json.loads(lin.tools.linux_file_manage({"action": "list", "path": str(tmp_path)}))
    assert out["success"] and out["items"][0]["name"] == "sub"
    out = json.loads(lin.tools.linux_file_manage({"action": "trash", "path": str(tmp_path / "nope")}))
    assert out["success"] is False


def test_selftest_classifier_linux_branch(monkeypatch):
    """selftest.py — общий скрипт для macOS/Windows/Linux; здесь форсируем ветку Linux,
    т.к. на CI/сборочной машине она уже совпадает (Linux), но проверяем классификатор явно."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("linuxselftest", "scripts/selftest.py")
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    # classify() проверяет ветки по приоритету if IS_WINDOWS / elif IS_LINUX — на реальном
    # Windows-раннере IS_WINDOWS уже True, поэтому форсируем обе переменные, а не только IS_LINUX,
    # иначе тест «форсирующий ветку Linux» на Windows CI тихо проверял бы ветку Windows.
    monkeypatch.setattr(st, "IS_LINUX", True)
    monkeypatch.setattr(st, "IS_WINDOWS", False)
    assert st.classify({"success": True}) == ("ok", "")
    s, note = st.classify({"success": False, "error": "Нужен xdotool (X11) для отправки сочетаний клавиш."})
    assert s == "missing"
    s, note = st.classify({"success": False, "error": "Автоматическое переключение темы поддерживается только на GNOME/GTK"})
    assert s == "unsupported"
    assert st.classify({"success": False, "error": "что-то странное сломалось"})[0] == "fail"
    assert all(h in load_plugin("jarvis-linux").tools.HANDLERS for h, _, _ in st.CHECKS_LINUX)


def test_selftest_checks_linux_reference_real_handlers():
    import importlib.util
    spec = importlib.util.spec_from_file_location("selftest_linux_candidates", "scripts/selftest.py")
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    assert all(h in load_plugin("jarvis-linux").tools.HANDLERS for h, _, _ in st.CHECKS_LINUX)
