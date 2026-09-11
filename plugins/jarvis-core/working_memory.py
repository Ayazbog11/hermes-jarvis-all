"""
Рабочая память (working memory) — короткоживущий слой между «сиюминутным контекстом»
(build_context() в __init__.py: время/батарея/таймеры) и долговременной базой знаний
(jarvis-brain: SQLite, ночная ревизия, дневник).

Идея скопирована у alex2772/kuni (см. docs/RESEARCH.md, docs/SOURCES.md — Round 7):
Kuni хранит `data/working_memory.md` — вещи, важные 1–3 дня (незавершённые задачи, обещания,
напоминания «спроси завтра»), которые не стоит класть в постоянную базу знаний, но и держать
в голове не по силам обычному ограниченному контексту диалога. Файл на каждый ход инъецируется
в промпт как `<things_to_remember>` и переживает перезапуски.

Здесь — тот же принцип, адаптированный к архитектуре Hermes-плагина (файл вместо C++ RAII-обвязки,
никакого отдельного демона): простой markdown-файл с TTL по записям (по умолчанию 3 дня, как у kuni),
который читает pre_llm_call (см. jarvis_working_memory + build_context) и который агент сам
дополняет/чистит инструментом `jarvis_working_memory`.

Формат хранения — JSON-список записей (не сырой markdown, чтобы TTL/устаревание считать надёжно),
но наружу (в контекст модели и в `.md`-экспорт) отдаётся как читаемый markdown-список, как у kuni.

Публичное API:
  add(text) -> dict
  list_active(max_age_days=3) -> list[dict]
  clear() -> dict
  render_context(max_age_days=3, limit=12) -> str   # пусто, если нечего показывать
  prune(max_age_days=3) -> int                      # убрать протухшие записи, вернуть их число
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

_LOCK = threading.RLock()


def _hermes_home() -> str:
    return os.path.expanduser(os.environ.get("HERMES_HOME") or "~/.hermes")


def _path() -> Path:
    base = os.environ.get("JARVIS_STATE_DIR")
    if not base:
        try:
            from plugins.plugin_storage import plugin_data_dir  # type: ignore

            base = str(plugin_data_dir("jarvis-core"))
        except Exception:  # вне Hermes (тесты, HUD, dev-запуск)
            base = os.path.join(_hermes_home(), "plugin-data", "jarvis-core")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p / "working_memory.json"


def _md_path() -> Path:
    """Человекочитаемая копия — как `data/working_memory.md` у kuni: можно открыть и поправить руками."""
    return _path().with_suffix(".md")


def _load() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list[dict]) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_path())
    try:
        lines = [f"- [{i.get('added_at', '')[:16].replace('T', ' ')}] {i.get('text', '')}" for i in items]
        _md_path().write_text("# Рабочая память JARVIS (1-3 дня)\n\n" + ("\n".join(lines) if lines else "_пусто_") + "\n",
                               encoding="utf-8")
    except OSError:
        pass  # md-копия — просто удобство для чтения руками, не критична


def add(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "Пустая запись для рабочей памяти"}
    with _LOCK:
        items = _load()
        items.append({"text": text, "added_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        _save(items)
    return {"success": True, "count": len(items)}


def list_active(max_age_days: float = 3.0) -> list[dict]:
    cutoff = time.time() - max_age_days * 86400
    out = []
    for item in _load():
        try:
            ts = time.mktime(time.strptime(item.get("added_at", ""), "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            ts = time.time()  # без даты — считаем свежей, не теряем
        if ts >= cutoff:
            out.append(item)
    return out


def prune(max_age_days: float = 3.0) -> int:
    """Удалить протухшие записи (старше max_age_days), вернуть их количество."""
    with _LOCK:
        before = _load()
        active = list_active(max_age_days)
        if len(active) != len(before):
            _save(active)
        return len(before) - len(active)


def clear() -> dict:
    with _LOCK:
        _save([])
    return {"success": True}


def render_context(max_age_days: float = 3.0, limit: int = 12) -> str:
    """Блок для инъекции в промпт — аналог `<things_to_remember>` у kuni."""
    items = list_active(max_age_days)[-limit:]
    if not items:
        return ""
    lines = "\n".join(f"- {i['text']}" for i in items)
    return ("[JARVIS working_memory] Незавершённые задачи/обещания за последние "
            f"{int(max_age_days)} дн. (обнови через jarvis_working_memory, когда сделано):\n{lines}")
