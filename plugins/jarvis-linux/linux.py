"""
Низкоуровневые помощники для работы с Linux.

Архитектура зеркалит plugins/jarvis-macos/mac.py и plugins/jarvis-windows/win.py,
но вместо единого системного API используется набор стандартных для рабочего стола
Linux консольных утилит (обычно уже установлены или ставятся одним пакетом):

  * wmctrl / xdotool     — окна, активное приложение, набор текста, хоткеи (X11)
  * pactl (PulseAudio/PipeWire) / amixer (ALSA)  — громкость
  * brightnessctl / xbacklight — яркость экрана
  * nmcli               — Wi-Fi/сеть (NetworkManager)
  * bluetoothctl        — Bluetooth (BlueZ)
  * upower / /sys/class/power_supply — батарея
  * systemctl / loginctl — sleep/выключение/блокировка экрана
  * grim (Wayland) / scrot / gnome-screenshot / spectacle / import (X11) — скриншоты
  * xclip / xsel / wl-copy / wl-paste — буфер обмена
  * playerctl            — управление медиаплеерами (MPRIS)
  * notify-send          — уведомления
  * espeak-ng / spd-say / piper — TTS (см. hud/tts.py)
  * xdg-open / gio open   — открытие файлов/URL стандартным приложением

Ни одна утилита не гарантированно есть на всех дистрибутивах — каждая функция
проверяет наличие нужного бинарника и явно сообщает, если он не найден, вместо
того чтобы падать с трудночитаемой ошибкой.

Каждая функция безопасна к ошибкам: возвращает (ok, output) и никогда не бросает
исключений наружу — обработчики инструментов оборачивают результат в JSON.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from shutil import which as _which
from typing import Iterable

IS_LINUX = sys.platform.startswith("linux")
IS_WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY"))
DESKTOP = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").lower()


class LinuxError(Exception):
    """Ошибка выполнения системной команды с человекочитаемым сообщением."""


# ───────────────────────────── запуск команд ───────────────────────────────

def run(cmd: list[str] | str, timeout: int = 30, check: bool = True, shell: bool = False,
        input_text: str | None = None) -> str:
    """Запустить команду и вернуть stdout (strip)."""
    if isinstance(cmd, str) and not shell:
        cmd = shlex.split(cmd)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=shell,
                               input=input_text)
    except FileNotFoundError as e:
        raise LinuxError(f"Команда не найдена: {cmd if isinstance(cmd, str) else cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise LinuxError(f"Команда превысила лимит {timeout}с") from e
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise LinuxError(err or f"Код возврата {proc.returncode}")
    return (proc.stdout or "").strip()


def which(binary: str) -> str | None:
    return _which(binary)


def require(binary: str, hint: str = "") -> None:
    """Бросить понятную ошибку, если утилита не установлена."""
    if not which(binary):
        msg = f"Нужна утилита «{binary}», но она не найдена в PATH."
        if hint:
            msg += f" Установите: {hint}"
        raise LinuxError(msg)


def require_linux() -> None:
    if not IS_LINUX:
        raise LinuxError("Этот инструмент работает только на Linux")


# ───────────────────────────── пути / кэш ───────────────────────────────────

def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "hermes"
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
    "pictures": "~/Pictures", "изображения": "~/Pictures",
    "videos": "~/Videos", "movies": "~/Videos", "music": "~/Music",
}


def resolve_target(target: str) -> str:
    t = target.strip()
    low = t.lower()
    if low in FOLDER_ALIASES:
        return str(Path(FOLDER_ALIASES[low]).expanduser())
    if "://" in t or low.startswith("mailto:"):
        return t
    if "." in t and " " not in t and "/" not in t and not t.startswith("~"):
        return "https://" + t
    return str(Path(t).expanduser())


def open_target(target: str) -> None:
    """xdg-open (стандарт freedesktop) с фолбэком на gio open."""
    if which("xdg-open"):
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif which("gio"):
        subprocess.Popen(["gio", "open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        raise LinuxError("Нужен xdg-open или gio (пакет: xdg-utils / glib2)")


def frontmost_app() -> str:
    """Класс/заголовок активного окна: xdotool (X11) или wmctrl; на «чистом» Wayland — недоступно."""
    if which("xdotool"):
        wid = run(["xdotool", "getactivewindow"], check=False).strip()
        if wid:
            name = run(["xdotool", "getwindowclassname", wid], check=False).strip()
            return name or run(["xdotool", "getwindowname", wid], check=False).strip()
    if which("wmctrl"):
        out = run(["wmctrl", "-a", ":ACTIVE:", "-v"], check=False)
        if out:
            return out.strip().splitlines()[-1]
    return ""


def running_apps() -> list[str]:
    if which("wmctrl"):
        out = run(["wmctrl", "-l"], check=False)
        return safe_list(" ".join(line.split()[3:]) for line in out.splitlines())
    out = run(["ps", "-eo", "comm="], check=False)
    return sorted(set(safe_list(out.splitlines())))


def detect_player(prefer: str = "auto") -> str:
    """Имя MPRIS-плеера (playerctl -l) по предпочтению или первому найденному."""
    if not which("playerctl"):
        return prefer if prefer != "auto" else ""
    out = run(["playerctl", "-l"], check=False)
    players = safe_list(out.splitlines())
    if not players:
        return ""
    if prefer != "auto":
        for p in players:
            if prefer.lower() in p.lower():
                return p
    return players[0]


def json_ok(**data) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False)


def json_err(message: str, **data) -> str:
    return json.dumps({"success": False, "error": message, **data}, ensure_ascii=False)


def safe_list(items: Iterable[str]) -> list[str]:
    return [i for i in (s.strip() for s in items) if i]


# ───────────────────────────── буфер обмена ─────────────────────────────────

def clipboard_get() -> str:
    if IS_WAYLAND and which("wl-paste"):
        return run(["wl-paste", "-n"], check=False)
    if which("xclip"):
        return run(["xclip", "-selection", "clipboard", "-o"], check=False)
    if which("xsel"):
        return run(["xsel", "--clipboard", "--output"], check=False)
    raise LinuxError("Нужен wl-clipboard (Wayland) или xclip/xsel (X11)")


def clipboard_set(text: str) -> None:
    if IS_WAYLAND and which("wl-copy"):
        subprocess.run(["wl-copy"], input=text.encode(), timeout=5)
        return
    if which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), timeout=5)
        return
    if which("xsel"):
        subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode(), timeout=5)
        return
    raise LinuxError("Нужен wl-clipboard (Wayland) или xclip/xsel (X11)")


# ───────────────────────────── ввод (набор текста / хоткеи) ─────────────────

def _no_display_hint(binary: str, err: str) -> LinuxError:
    """xdotool/wmctrl молча ссылаются на 'xdo instance'/'Can't open display' без $DISPLAY —
    это частый случай headless-сессии (SSH без X forwarding, чистый Wayland без XWayland,
    systemd-сервис без графической сессии). Подсказка должна явно называть инструмент и причину,
    а не пробрасывать сырое сообщение xdotool дальше."""
    low = err.lower()
    if "can't open display" in low or "xdo instance" in low or not os.environ.get("DISPLAY"):
        return LinuxError(
            f"{binary}: нет доступа к X-дисплею (DISPLAY={os.environ.get('DISPLAY') or 'не задан'}). "
            "Нужна активная графическая сессия (X11 или XWayland); из SSH/systemd-сервиса без "
            "графического окружения этот инструмент недоступен."
        )
    return LinuxError(f"{binary}: {err}")


def type_text(text: str) -> None:
    if which("ydotool"):
        run(["ydotool", "type", "--", text], check=True, timeout=15)
        return
    if not IS_WAYLAND and which("xdotool"):
        try:
            run(["xdotool", "type", "--clearmodifiers", "--", text], check=True, timeout=15)
        except LinuxError as e:
            raise _no_display_hint("xdotool", str(e)) from e
        return
    raise LinuxError(
        "Нужен xdotool (X11) или ydotool (Wayland/X11, требует запущенный ydotoold). "
        "Установите: sudo apt install xdotool  (или ydotool)."
    )


def send_keystroke(combo: str) -> None:
    """combo в формате xdotool: 'ctrl+shift+t', 'Return', 'super+d'…"""
    if which("ydotool"):
        # ydotool key принимает коды клавиш, а не имена — проще положиться на xdotool, если он есть,
        # и явно сообщить об ограничении иначе.
        if which("xdotool"):
            try:
                run(["xdotool", "key", "--clearmodifiers", combo], check=True, timeout=10)
            except LinuxError as e:
                raise _no_display_hint("xdotool", str(e)) from e
            return
        raise LinuxError("Для произвольных сочетаний клавиш на Wayland без xdotool нужна поддержка ydotool key <keycode> — не реализовано для имён клавиш.")
    if which("xdotool"):
        try:
            run(["xdotool", "key", "--clearmodifiers", combo], check=True, timeout=10)
        except LinuxError as e:
            raise _no_display_hint("xdotool", str(e)) from e
        return
    raise LinuxError("Нужен xdotool (X11) для отправки сочетаний клавиш.")


# ───────────────────────────── audio helpers ────────────────────────────────

def _pactl_sink() -> str:
    out = run(["pactl", "get-default-sink"], check=False)
    return out.strip() or "@DEFAULT_SINK@"
