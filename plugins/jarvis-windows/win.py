"""
Низкоуровневые помощники для работы с Windows.

Архитектура зеркалит plugins/jarvis-macos/mac.py, только вместо AppleScript/osascript
используются два канала:
  * powershell   — PowerShell 5.1+ (встроен в Windows 10/11), включая inline C#/WinRT
                    через Add-Type — аналог "osascript" из мира macOS;
  * shell        — стандартные утилиты Windows (start, explorer, netsh, shutdown, schtasks…);
  * файлы        — каталог кэша для скриншотов и т.п.

Каждая функция безопасна к ошибкам: возвращает (ok, output) и никогда не бросает
исключений наружу — обработчики инструментов оборачивают результат в JSON.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import subprocess
import time
from pathlib import Path
from typing import Iterable

IS_WINDOWS = platform.system() == "Windows"


class WinError(Exception):
    """Ошибка выполнения системной команды с человекочитаемым сообщением."""


# ───────────────────────────── запуск команд ───────────────────────────────

def run(cmd: list[str] | str, timeout: int = 30, check: bool = True, shell: bool = False) -> str:
    """Запустить команду и вернуть stdout (strip).

    cmd — список аргументов (предпочтительно) или строка (будет разобрана shlex, если shell=False).
    """
    if isinstance(cmd, str) and not shell:
        cmd = shlex.split(cmd, posix=False)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=shell,
                               creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
    except FileNotFoundError as e:
        raise WinError(f"Команда не найдена: {cmd if isinstance(cmd, str) else cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise WinError(f"Команда превысила лимит {timeout}с") from e
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise WinError(err or f"Код возврата {proc.returncode}")
    return (proc.stdout or "").strip()


def powershell(script: str, timeout: int = 30, check: bool = True) -> str:
    """Выполнить блок PowerShell (5.1+, встроен в Windows) и вернуть stdout.

    Используется как аналог osascript: управление приложениями, окна, громкость,
    яркость, буфер обмена, TTS, тосты и т.п. — через .NET / WinRT / WMI из PowerShell.
    """
    cmd = [
        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-Command",
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $OutputEncoding=[Text.Encoding]::UTF8; " + script,
    ]
    try:
        return run(cmd, timeout=timeout, check=check)
    except WinError as e:
        msg = str(e)
        low = msg.lower()
        if "access is denied" in low or "отказано в доступе" in low or "requested operation requires elevation" in low:
            raise WinError(
                "Отказано в доступе — нужны права администратора. Запустите JARVIS/терминал «от имени администратора» "
                "или воспользуйтесь другим действием."
            ) from e
        if "execution of scripts is disabled" in low or "выполнение сценариев отключено" in low:
            raise WinError(
                "PowerShell блокирует выполнение сценариев. Выполните один раз от администратора: "
                "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned"
            ) from e
        raise


def which(binary: str) -> str | None:
    """Путь к бинарнику или None."""
    from shutil import which as _which
    return _which(binary)


def as_ps(value) -> str:
    """Экранировать значение для вставки в одинарные кавычки PowerShell."""
    return "'" + str(value).replace("'", "''") + "'"


def hermes_home() -> Path:
    """%HERMES_HOME% (нативный Windows-инсталлятор Hermes) или %LOCALAPPDATA%\\hermes."""
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "hermes"
    return Path.home() / ".hermes"


def cache_dir(sub: str = "") -> Path:
    base = Path(os.environ["JARVIS_CACHE_DIR"]).expanduser() if os.environ.get("JARVIS_CACHE_DIR") else hermes_home() / "cache" / "jarvis"
    if sub:
        base = base / sub
    base.mkdir(parents=True, exist_ok=True)
    return base


def stamp(prefix: str, ext: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}.{ext}"


# ───────────────────────────── типовые действия ────────────────────────────

FOLDER_ALIASES = {
    "downloads": "~/Downloads", "загрузки": "~/Downloads",
    "desktop": "~/Desktop", "рабочий стол": "~/Desktop",
    "documents": "~/Documents", "документы": "~/Documents",
    "home": "~", "домашняя": "~",
    "applications": "C:/ProgramData/Microsoft/Windows/Start Menu/Programs", "программы": "C:/ProgramData/Microsoft/Windows/Start Menu/Programs",
    "pictures": "~/Pictures", "изображения": "~/Pictures",
    "videos": "~/Videos", "movies": "~/Videos", "music": "~/Music",
}


def resolve_target(target: str) -> str:
    """URL оставить как есть; папки-алиасы и ~ раскрыть."""
    t = target.strip()
    low = t.lower()
    if low in FOLDER_ALIASES:
        return str(Path(FOLDER_ALIASES[low]).expanduser())
    if "://" in t or low.startswith("mailto:"):
        return t
    if "." in t and " " not in t and "/" not in t and "\\" not in t and not t.startswith("~"):
        return "https://" + t
    return str(Path(t).expanduser())


def frontmost_app() -> str:
    """Заголовок и имя процесса активного окна (через WinAPI GetForegroundWindow)."""
    out = powershell(
        "Add-Type -Namespace W -Name U -MemberDefinition '"
        "[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();"
        "[DllImport(\"user32.dll\")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);'; "
        "$h=[W.U]::GetForegroundWindow(); $pid=0; [W.U]::GetWindowThreadProcessId($h,[ref]$pid) | Out-Null; "
        "(Get-Process -Id $pid -ErrorAction SilentlyContinue).ProcessName",
        check=False,
    )
    return out.strip()


def running_apps() -> list[str]:
    out = powershell(
        "Get-Process | Where-Object { $_.MainWindowTitle } | Select-Object -ExpandProperty ProcessName -Unique",
        check=False,
    )
    return safe_list(out.splitlines())


def detect_player(prefer: str = "auto") -> str:
    if prefer in ("music", "spotify", "media"):
        return prefer
    apps = {a.lower() for a in running_apps()}
    if "spotify" in apps:
        return "spotify"
    return "media"


def json_ok(**data) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False)


def json_err(message: str, **data) -> str:
    return json.dumps({"success": False, "error": message, **data}, ensure_ascii=False)


def require_windows() -> None:
    if not IS_WINDOWS:
        raise WinError("Этот инструмент работает только на Windows")


def safe_list(items: Iterable[str]) -> list[str]:
    return [i for i in (s.strip() for s in items) if i]
