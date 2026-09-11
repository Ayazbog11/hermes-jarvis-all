"""Тесты plugins/jarvis-core/working_memory.py — кратковременная рабочая память (идея из kuni)."""

from __future__ import annotations

import json
import time

from conftest import load_plugin


def _core(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    return load_plugin("jarvis-core")


def test_add_empty_text_fails(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    r = core.working_memory.add("")
    assert r["success"] is False


def test_add_and_list(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.clear()
    r = core.working_memory.add("Напомнить про дедлайн Atlas")
    assert r["success"] is True
    items = core.working_memory.list_active()
    assert len(items) == 1
    assert items[0]["text"] == "Напомнить про дедлайн Atlas"


def test_writes_readable_markdown_copy(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.clear()
    core.working_memory.add("Купить корм коту")
    md = core.working_memory._md_path().read_text(encoding="utf-8")
    assert "Купить корм коту" in md


def test_prune_removes_old_entries(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.clear()
    old_ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 10 * 86400))
    core.working_memory._save([{"text": "старая задача", "added_at": old_ts}])
    core.working_memory.add("свежая задача")
    removed = core.working_memory.prune(max_age_days=3)
    assert removed == 1
    items = core.working_memory.list_active()
    assert len(items) == 1 and items[0]["text"] == "свежая задача"


def test_render_context_empty_when_nothing_active(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.clear()
    assert core.working_memory.render_context() == ""


def test_render_context_lists_active_items(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.clear()
    core.working_memory.add("Позвонить маме")
    ctx = core.working_memory.render_context()
    assert "Позвонить маме" in ctx
    assert "[JARVIS working_memory]" in ctx


def test_clear(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.add("что-то")
    core.working_memory.clear()
    assert core.working_memory.list_active() == []


# ─────────────────────── jarvis_working_memory инструмент ──────────────────

def test_tool_add_action(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.clear()
    out = json.loads(core.tool_jarvis_working_memory({"action": "add", "text": "Проверить почту"}))
    assert out["success"] is True


def test_tool_list_action(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.clear()
    core.working_memory.add("Заплатить за интернет")
    out = json.loads(core.tool_jarvis_working_memory({"action": "list"}))
    assert out["success"] is True and out["count"] == 1


def test_tool_clear_action(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.add("Что-то временное")
    out = json.loads(core.tool_jarvis_working_memory({"action": "clear"}))
    assert out["success"] is True
    assert core.working_memory.list_active() == []


def test_tool_unknown_action(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    out = json.loads(core.tool_jarvis_working_memory({"action": "bogus"}))
    assert out["success"] is False


def test_build_context_includes_working_memory(tmp_path, monkeypatch):
    core = _core(tmp_path, monkeypatch)
    core.working_memory.clear()
    core.working_memory.add("Дописать отчёт")
    ctx = core.build_context()
    assert "Дописать отчёт" in ctx
