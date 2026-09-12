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

Профили провайдеров (Round 12): у Hermes уже можно настроить сразу несколько провайдеров
(OpenRouter/Anthropic/OpenAI/Gemini/xAI/Ollama и т.д., см. docs/AI-MODELS.md) и переключаться
между ними через `hermes model`/`/model` — но каждый раз вспоминать «какой ключ переменной
окружения у какого провайдера» и вбивать 3-4 значения вручную неудобно. `save_profile()`/
`apply_profile()` просто запоминают такой набор значений (provider/base_url/default model +
опционально сам API-ключ — `hermes config set OPENROUTER_API_KEY ...` и т.п. уже сам решает,
что это секрет, и кладёт в `.env`, а не в `config.yaml`) под именем и применяют его одной
кнопкой в HUD — быстрое «переключиться на OpenRouter» / «переключиться на локальный Ollama»
без похода в `hermes model` за 4 отдельных значения каждый раз.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

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

# ── Профили провайдеров: набор ключей config.yaml/.env, которые можно сохранить под именем
# и применить одной кнопкой. Ключи API — те же имена переменных окружения, что и в
# config/.env.example и docs/AI-MODELS.md (полный список провайдеров — Hermes docs "AI Providers").
PROFILE_ALLOWED_KEYS: dict[str, str] = {
    "model.provider": "Провайдер модели чата (nous | openrouter | anthropic | openai-api | gemini | custom …)",
    "model.default": "Модель чата (напр. anthropic/claude-3.7-sonnet, openrouter/auto, qwen3:8b)",
    "model.base_url": "Свой OpenAI-совместимый endpoint (для custom/Ollama и т.п.)",
    "OPENROUTER_API_KEY": "Ключ OpenRouter",
    "ANTHROPIC_API_KEY": "Ключ Anthropic",
    "OPENAI_API_KEY": "Ключ OpenAI",
    "GEMINI_API_KEY": "Ключ Google Gemini",
    "XAI_API_KEY": "Ключ xAI (Grok)",
    "GROQ_API_KEY": "Ключ Groq",
    "DEEPSEEK_API_KEY": "Ключ DeepSeek",
    "FIREWORKS_API_KEY": "Ключ Fireworks AI",
}
_SECRET_KEYS = {k for k in PROFILE_ALLOWED_KEYS if k.isupper()}  # переменные окружения — секреты, не показываем в списке


def _hermes_home() -> Path:
    default = (os.environ.get("LOCALAPPDATA", "") + "/hermes") if os.name == "nt" else "~" + "/.hermes"
    return Path(os.environ.get("HERMES_HOME") or default).expanduser()


def _profiles_path() -> Path:
    p = _hermes_home() / "jarvis" / "model_profiles.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_profiles() -> dict:
    p = _profiles_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_profiles(data: dict) -> None:
    p = _profiles_path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # секреты (API-ключи) хранятся в этом файле — best-effort chmod 600, как у telegram_userbot.py
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def list_profiles() -> dict:
    """Список сохранённых профилей — значения API-ключей маскируются (…последние 4 символа),

    полный ключ никогда не уходит в HUD-фронтенд лишний раз без необходимости."""
    profiles = _load_profiles()
    out = {}
    for name, fields in profiles.items():
        shown = {}
        for k, v in fields.items():
            if k in _SECRET_KEYS and v:
                shown[k] = f"…{v[-4:]}" if len(v) > 4 else "…"
            else:
                shown[k] = v
        out[name] = shown
    return {"success": True, "profiles": out, "fields": PROFILE_ALLOWED_KEYS}


def save_profile(name: str, fields: dict) -> dict:
    """Сохранить набор значений под именем профиля (перезаписывает, если имя уже есть)."""
    name = (name or "").strip()
    if not name:
        return {"success": False, "error": "Нужно имя профиля"}
    clean = {k: (v or "").strip() for k, v in (fields or {}).items() if k in PROFILE_ALLOWED_KEYS and (v or "").strip()}
    if not clean:
        return {"success": False, "error": "Нет ни одного заполненного поля"}
    profiles = _load_profiles()
    profiles[name] = clean
    _save_profiles(profiles)
    return {"success": True, "name": name, "fields": list(clean.keys())}


def delete_profile(name: str) -> dict:
    profiles = _load_profiles()
    if name not in profiles:
        return {"success": False, "error": f"Профиль не найден: {name}"}
    del profiles[name]
    _save_profiles(profiles)
    return {"success": True}


def apply_profile(name: str, timeout: float = 20.0) -> dict:
    """Применить сохранённый профиль — по очереди `hermes config set <ключ> <значение>` для

    каждого сохранённого поля (тот же официальный путь, что и apply одного поля/`jarvis ollama use`).
    Не откатывает при частичной неудаче (в отличие от `jarvis ollama use`) — здесь нет единого
    «health check» одной модели, т.к. профиль может одновременно менять провайдера и ключ; вместо
    этого возвращается детальный отчёт по каждому применённому ключу, чтобы пользователь видел,
    что именно не применилось.
    """
    profiles = _load_profiles()
    if name not in profiles:
        return {"success": False, "error": f"Профиль не найден: {name}"}
    hermes = _hermes_bin()
    if not hermes:
        return {"success": False, "error": "hermes не найден в PATH"}
    results = {}
    ok_all = True
    for key, value in profiles[name].items():
        try:
            out = subprocess.run([hermes, "config", "set", key, value], capture_output=True, text=True, timeout=timeout)
            success = out.returncode == 0
            results[key] = {"success": success, "error": None if success else (out.stderr or out.stdout or "").strip()[:200]}
        except (subprocess.TimeoutExpired, OSError) as e:
            results[key] = {"success": False, "error": str(e)}
        ok_all = ok_all and results[key]["success"]
    return {"success": ok_all, "name": name, "results": results}


def _hermes_bin() -> str | None:
    """Найти исполняемый файл `hermes`.

    Сначала пробуем PATH (быстрый путь, обычно работает). Если `shutil.which`
    не находит — это НЕ обязательно значит, что Hermes не установлен: HUD-сервер
    на Windows часто запускается из Scheduled Task при входе в систему, а
    `[Environment]::SetEnvironmentVariable(..., "User")` из install.ps1 подхватывается
    только НОВЫМИ процессами — уже запущенный при логине HUD может унаследовать
    устаревший PATH без $HERMES_HOME\\...\\bin. То же самое случается и после
    самообновления Hermes через Desktop UI (см. апстрим-issue NousResearch/hermes-agent
    #91563 — обновление иногда удаляет hermes-agent/bin, оставляя PATH указывающим
    в никуда) — итог одинаков: `shutil.which("hermes")` возвращает None, хотя
    Hermes реально установлен, и HUD-кнопка смены модели молча перестаёт работать.
    Поэтому при провале PATH дополнительно проверяем известные места, куда
    install.ps1/install.sh кладут бинарник, напрямую по $HERMES_HOME.
    """
    found = shutil.which("hermes")
    if found:
        return found
    home = _hermes_home()
    candidates = (
        [
            home / "hermes-agent" / "bin" / "hermes.exe",
            home / "hermes-agent" / "venv" / "Scripts" / "hermes.exe",
            home / "bin" / "hermes.exe",
            home / "bin" / "hermes.cmd",
        ]
        if os.name == "nt"
        else [
            home / "hermes-agent" / "bin" / "hermes",
            home / "hermes-agent" / "venv" / "bin" / "hermes",
            Path.home() / ".local" / "bin" / "hermes",
        ]
    )
    for c in candidates:
        if c.exists():
            return str(c)
    return None


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
