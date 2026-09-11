"""
Голосовые сообщения JARVIS: текст → аудиофайл, который можно приложить к ответу
или отправить в мессенджер через jarvis_send_message(action=send_file).

Почему переиспользуем hud/tts.py, а не пишем новый синтез (аудит GitHub, Раунд 7 —
Kuni/kuni использует ровно этот паттерн: один VoiceGenerator на весь проект, PCM→OGG/Opus
транскодируется при необходимости, никакого дублирования движков TTS): у HUD уже есть
рабочий каскад движков (edge-tts → macOS say → Windows SAPI → Linux espeak-ng) с кэшированием
и общей конфигурацией голоса из config.yaml (tts.edge.voice/tts.speed). Дублировать этот выбор
и код здесь означало бы поддерживать два независимых пути синтеза речи, которые могут разойтись.

Публичное API:
  generate(text, out_dir=None) -> dict  {"success": bool, "path"?: str, "mime"?: str, "error"?: str}
"""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

_HUD_TTS = None


def _hermes_home() -> str:
    """Каталог данных Hermes: $HERMES_HOME или ~/.hermes.

    Дублирует state.hermes_home() (не импортируем state.py через относительный импорт,
    потому что hud/server.py подгружает этот файл как отдельный модуль по пути, а не как
    часть пакета plugins.jarvis-core — относительный `from . import state` там упадёт с
    ImportError: attempted relative import with no known parent package).
    """
    return os.path.expanduser(os.environ.get("HERMES_HOME") or "~/.hermes")


def _load_hud_tts():
    """Импортировать hud/tts.py по пути (тот же модуль, что использует HUD-сервер для озвучки).

    HUD ставится рядом с этим плагином при установке ($JARVIS_HOME/hud/tts.py), а в дереве
    репозитория (dev/тесты) — на уровень выше (hud/tts.py, соседний с plugins/). Пробуем оба.
    """
    global _HUD_TTS
    if _HUD_TTS is not None:
        return _HUD_TTS
    here = Path(__file__).resolve().parent
    for candidate in (
        Path(_hermes_home()) / "jarvis" / "hud" / "tts.py",  # установлено
        here.parent.parent / "hud" / "tts.py",                    # дерево репозитория
    ):
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("jarvis_core_hud_tts", candidate)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _HUD_TTS = mod
                return _HUD_TTS
    return None


def generate(text: str, out_dir: str | None = None) -> dict:
    """Синтезировать текст в аудиофайл и сохранить его на диск. Никогда не бросает исключений."""
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "Пустой текст для голосового сообщения"}
    tts = _load_hud_tts()
    if tts is None:
        return {"success": False, "error": "hud/tts.py недоступен — HUD не установлен или не найден рядом с плагином"}
    try:
        result = tts.synthesize(text)
    except Exception as e:  # синтез не должен ронять инструмент
        return {"success": False, "error": f"Ошибка синтеза речи: {e}"}
    if not result:
        return {"success": False, "error": f"Нет доступного движка TTS (engine={tts.engine()}) — "
                                            f"установите edge-tts (pip install edge-tts) или используйте системный синтез"}
    audio, mime = result
    ext = {"audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/wav": "wav"}.get(mime, "mp3")
    target_dir = Path(out_dir).expanduser() if out_dir else Path(_hermes_home()) / "cache" / "jarvis" / "voice"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / f"voice_{int(time.time() * 1000)}.{ext}"
        out_path.write_bytes(audio)
    except OSError as e:
        return {"success": False, "error": f"Не удалось сохранить аудиофайл: {e}"}
    return {"success": True, "path": str(out_path), "mime": mime, "chars": len(text)}
