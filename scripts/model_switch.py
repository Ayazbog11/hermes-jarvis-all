#!/usr/bin/env python3
"""
model_switch.py — тонкая обёртка над `hermes config get/set` для HUD-виджета
«выбор модели ИИ» (см. hud/server.py: GET/POST /api/model, hud/static/index.html).

Зачем отдельный модуль, а не звать `hermes config` прямо из hud/server.py: список
разрешённых ключей и их подписи для UI нужны и HUD, и потенциально CLI/трею — держим
их в одном месте. Разрешён только строго ограниченный набор ключей (ALLOWED_KEYS) —
HUD слушает localhost/сеть пользователя, но всё равно не должен позволять произвольную
запись в config.yaml по имени ключа с фронтенда.

Hermes уже поддерживает независимый выбор модели на задачу — это ровно тот механизм,
который мы здесь просто показываем/переключаем одной кнопкой вместо похода в
`hermes model` / ручной правки config.yaml:
  - model.default              — основная модель чата
  - auxiliary.vision.model      — модель для распознавания экрана/фото (см. docs/AI-MODELS.md)
  - auxiliary.compression.model — модель для сжатия длинной истории диалога
  - auxiliary.title_generation.model — модель, которая придумывает заголовки сессий
  - image_gen.provider / image_gen.model — генерация картинок (jarvis_image, hud "photo")
  - tts.provider                 — озвучка (jarvis_voice_note, HUD "голосовое")
"""

from __future__ import annotations

import shutil
import subprocess

# label -> (config-ключ, подсказка/плейсхолдер для UI)
ALLOWED_KEYS: dict[str, tuple[str, str]] = {
    "chat_model": ("model.default", "напр. anthropic/claude-3.7-sonnet, openai/gpt-4o"),
    "vision_model": ("auxiliary.vision.model", "напр. openai/gpt-4o, google/gemini-2.5-flash"),
    "compression_model": ("auxiliary.compression.model", "модель для сжатия истории диалога"),
    "title_model": ("auxiliary.title_generation.model", "модель для заголовков сессий"),
    "image_provider": ("image_gen.provider", "nous | fal | openai | xai | krea | openrouter | meta-ai | openai-compatible"),
    "image_model": ("image_gen.model", "модель генерации картинок (зависит от провайдера)"),
    "tts_provider": ("tts.provider", "провайдер озвучки (edge-tts и др. — см. docs)"),
}


def _hermes_bin() -> str | None:
    return shutil.which("hermes")


def is_available() -> bool:
    return _hermes_bin() is not None


def get_all(timeout: float = 10.0) -> dict:
    """Прочитать текущие значения всех разрешённых ключей через `hermes config get`.

    Никогда не бросает исключения — при отсутствии hermes/ошибке чтения конкретного ключа
    просто оставляет пустую строку для него, чтобы HUD показал плейсхолдер, а не сломался.
    """
    hermes = _hermes_bin()
    if not hermes:
        return {"success": False, "error": "hermes не найден в PATH", "values": {}}
    values: dict[str, str] = {}
    for label, (key, _hint) in ALLOWED_KEYS.items():
        try:
            out = subprocess.run([hermes, "config", "get", key], capture_output=True, text=True, timeout=timeout)
            values[label] = out.stdout.strip() if out.returncode == 0 else ""
        except (subprocess.TimeoutExpired, OSError):
            values[label] = ""
    return {"success": True, "values": values, "fields": {k: v[1] for k, v in ALLOWED_KEYS.items()}}


def set_value(label: str, value: str, timeout: float = 20.0) -> dict:
    """Установить один из разрешённых ключей через `hermes config set` (официальный способ —
    не редактируем config.yaml руками, чтобы не сломать формат/комментарии)."""
    if label not in ALLOWED_KEYS:
        return {"success": False, "error": f"Неизвестный параметр модели: {label}"}
    key, _hint = ALLOWED_KEYS[label]
    value = (value or "").strip()
    if not value:
        return {"success": False, "error": "Пустое значение"}
    hermes = _hermes_bin()
    if not hermes:
        return {"success": False, "error": "hermes не найден в PATH"}
    try:
        out = subprocess.run([hermes, "config", "set", key, value], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "hermes config set не ответил вовремя"}
    except OSError as e:
        return {"success": False, "error": str(e)}
    if out.returncode != 0:
        return {"success": False, "error": (out.stderr or out.stdout or "hermes config set завершился с ошибкой").strip()}
    return {"success": True, "key": key, "value": value}
