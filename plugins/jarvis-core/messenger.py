"""
Отправка сообщений в мессенджеры (Telegram/Discord/Slack/Signal/WhatsApp/…) через
встроенный `hermes send` — без повторного ввода токенов ботов и без запущенного gateway.

Почему так, а не свой Telegram-бот/http-клиент (аудит GitHub, Раунд 7, см. docs/RESEARCH.md):
Hermes Agent уже умеет `hermes send --to <платформа>[:chat_id[:thread_id]] "текст"` — это
кроссплатформенный «curl для уведомлений», который переиспользует те же адаптеры и учётные
данные (файл `.env` и `config.yaml` внутри $HERMES_HOME), что и `hermes gateway`. Реализовывать
собственный HTTP-клиент к Bot API Telegram/Discord значило бы: (1) дублировать код, который
уже отлажен внутри Hermes; (2) завести вторую поверхность конфигурации токенов; (3) сломаться
при следующем обновлении Hermes, если формат API поменяется. Вместо этого — тонкая, отказоустойчивая
обёртка над CLI-командой, ровно как и `scripts/ollama_local.py` оборачивает `hermes config`.

Публичное API:
  send(target, text, subject=None, quiet=True, timeout=20) -> dict
  send_file(target, path, caption=None, quiet=True, timeout=60) -> dict
  list_targets(platform=None, timeout=10) -> dict
  is_available() -> bool   (кэшируется; reset_cache() — для тестов)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

_CACHE_TTL = 30.0
_available_cache: tuple[float, bool] | None = None


def reset_cache() -> None:
    global _available_cache
    _available_cache = None


def _hermes_bin() -> str | None:
    """Найти `hermes`: сперва PATH, затем известные install-пути под $HERMES_HOME.

    `shutil.which` в одиночку не всегда достаточен на Windows: HUD/gateway часто
    запущены из процесса (Scheduled Task при логине), унаследовавшего PATH,
    сохранённый ДО того, как install.ps1 дописал в него bin-каталог Hermes
    (`[Environment]::SetEnvironmentVariable(..., "User")` подхватывают только новые
    процессы), либо после самообновления Hermes через Desktop UI, которое иногда
    удаляет hermes-agent/bin, не обновляя PATH (см. апстрим NousResearch/hermes-agent
    #91563). В обоих случаях `hermes` реально установлен, но PATH об этом не знает —
    поэтому при провале PATH проверяем и типовые пути установки напрямую.
    """
    found = shutil.which("hermes")
    if found:
        return found
    default = (os.environ.get("LOCALAPPDATA", "") + "/hermes") if os.name == "nt" else "~" + "/.hermes"
    home = Path(os.environ.get("HERMES_HOME") or default).expanduser()
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
    """Есть ли бинарник `hermes` в PATH — дёшево кэшируется, чтобы не дёргать shutil.which на каждый вызов."""
    global _available_cache
    now = time.time()
    if _available_cache is not None and now - _available_cache[0] < _CACHE_TTL:
        return _available_cache[1]
    ok = _hermes_bin() is not None
    _available_cache = (now, ok)
    return ok


def send(target: str, text: str, subject: str | None = None, quiet: bool = True, timeout: float = 20.0) -> dict:
    """Отправить сообщение через `hermes send --to <target> [--subject ...] --json [--quiet] "<text>"`.

    target — "telegram" (домашний канал), "telegram:-100123...", "discord:#ops",
    "signal:+15551234567" и т.п. (см. docs Hermes «Pipe Script Output to Messaging Platforms»).
    Возвращает {"success": bool, "error"?: str, ...} — никогда не бросает исключений.
    """
    hermes = _hermes_bin()
    if not hermes:
        return {"success": False, "error": "`hermes` не найден в PATH — команда send недоступна в этом окружении"}
    target = (target or "").strip()
    text = (text or "").strip()
    if not target:
        return {"success": False, "error": "Не указана цель (target): telegram, discord:#канал, telegram:chat_id…"}
    if not text:
        return {"success": False, "error": "Пустое сообщение"}
    cmd = [hermes, "send", "--to", target, "--json"]
    if subject:
        cmd += ["--subject", subject]
    if quiet:
        cmd.append("--quiet")
    cmd.append(text)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"hermes send не ответил за {timeout:.0f}с"}
    except OSError as e:
        return {"success": False, "error": f"не удалось запустить hermes send: {e}"}
    out = (proc.stdout or "").strip()
    if proc.returncode == 0:
        try:
            data = json.loads(out) if out else {}
        except ValueError:
            data = {}
        return {"success": True, "target": target, **(data if isinstance(data, dict) else {})}
    # коды возврата по конвенции hermes send: 1 — сбой доставки, 2 — ошибка использования/конфига
    err = (proc.stderr or out or "неизвестная ошибка").strip()
    hint = ""
    if proc.returncode == 2:
        hint = " (проверьте, что платформа настроена: hermes send --list)"
    return {"success": False, "error": (err[-500:] + hint), "target": target, "exit_code": proc.returncode}


def send_file(target: str, path: str, caption: str | None = None, quiet: bool = True, timeout: float = 60.0) -> dict:
    """Отправить файл/фото/голосовое (voice note, скриншот, сгенерированную картинку, документ и т.п.).

    Использует директиву `MEDIA:<путь>` в теле `hermes send` (см. docs Hermes «Pipe Script Output to
    Messaging Platforms» — `hermes send --to telegram "MEDIA:/tmp/screenshot.png"`, тот же CLI, что и
    send() для текста, поэтому голосовые/фото/видео/документы отправляются той же цепочкой без
    отдельного HTTP-клиента для каждой платформы. caption (если задан) идёт перед MEDIA: как обычный текст.
    """
    hermes = _hermes_bin()
    if not hermes:
        return {"success": False, "error": "`hermes` не найден в PATH — команда send недоступна в этом окружении"}
    target = (target or "").strip()
    path = (path or "").strip()
    if not target:
        return {"success": False, "error": "Не указана цель (target): telegram, discord:#канал, telegram:chat_id…"}
    if not path:
        return {"success": False, "error": "Не указан путь к файлу"}
    p = Path(path).expanduser()
    if not p.is_file():
        return {"success": False, "error": f"Файл не найден: {p}"}
    body = f"{caption.strip()} MEDIA:{p}" if caption and caption.strip() else f"MEDIA:{p}"
    cmd = [hermes, "send", "--to", target, "--json"]
    if quiet:
        cmd.append("--quiet")
    cmd.append(body)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"hermes send не ответил за {timeout:.0f}с (большой файл?)"}
    except OSError as e:
        return {"success": False, "error": f"не удалось запустить hermes send: {e}"}
    out = (proc.stdout or "").strip()
    if proc.returncode == 0:
        try:
            data = json.loads(out) if out else {}
        except ValueError:
            data = {}
        return {"success": True, "target": target, "file": str(p), **(data if isinstance(data, dict) else {})}
    err = (proc.stderr or out or "неизвестная ошибка").strip()
    hint = ""
    if proc.returncode == 2:
        hint = " (проверьте, что платформа настроена: hermes send --list)"
    return {"success": False, "error": (err[-500:] + hint), "target": target, "exit_code": proc.returncode}


def list_targets(platform: str | None = None, timeout: float = 10.0) -> dict:
    """Список настроенных целей доставки (`hermes send --list [платформа] --json`)."""
    hermes = _hermes_bin()
    if not hermes:
        return {"success": False, "error": "`hermes` не найден в PATH"}
    cmd = [hermes, "send", "--list", "--json"]
    if platform:
        cmd.append(platform)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"hermes send --list не ответил за {timeout:.0f}с"}
    except OSError as e:
        return {"success": False, "error": f"не удалось запустить hermes send: {e}"}
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return {"success": False, "error": (proc.stderr or out or "неизвестная ошибка")[-500:]}
    try:
        data = json.loads(out) if out else {}
    except ValueError:
        data = {"raw": out}
    if isinstance(data, list):
        return {"success": True, "targets": data}
    if isinstance(data, dict):
        return {"success": True, **data}
    return {"success": True, "targets": []}
