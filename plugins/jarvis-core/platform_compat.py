"""
Кроссплатформенный слой jarvis-core: то немногое, что ядро делает "руками" напрямую
(без похода через jarvis-macos/jarvis-windows/jarvis-linux инструменты) — контекст хода,
таймеры, watchdog. Раньше это было зашито под macOS (osascript/pmset/screencapture);
теперь есть три полноценные реализации: macOS, Windows, Linux (X11/Wayland, best-effort —
конкретные утилиты могут отсутствовать в минимальных дистрибутивах, тогда используется
безопасный fallback на "недоступно").

Каждая функция никогда не бросает исключений и возвращает "пустое" значение,
если платформа/окружение не поддерживает возможность.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def _run(cmd: list, timeout: float = 5, **kw) -> str:
    try:
        kwargs = {"capture_output": True, "text": True, "timeout": timeout}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        kwargs.update(kw)
        return subprocess.run(cmd, **kwargs).stdout or ""
    except Exception:
        return ""


def _powershell(script: str, timeout: float = 10) -> str:
    return _run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    ).strip()


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def _is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))


# ══════════════════════════════ батарея ═════════════════════════════════════

def battery_brief() -> str:
    """Краткая строка вида '82% ⚡' для контекста хода."""
    pct, charging = battery_state()
    if pct is None:
        return ""
    return f"{pct}%" + (" ⚡" if charging else "")


def battery_state() -> tuple[int | None, bool]:
    if IS_MAC:
        out = _run(["pmset", "-g", "batt"], timeout=3)
        pct = None
        for tok in out.replace(";", " ").split():
            if tok.endswith("%") and tok[:-1].isdigit():
                pct = int(tok[:-1])
        charging = ("charging" in out and "discharging" not in out) or "AC Power" in out
        return pct, charging
    if IS_WINDOWS:
        out = _powershell(
            "$b = Get-WmiObject Win32_Battery -ErrorAction SilentlyContinue; "
            "if ($b) { \"$($b.EstimatedChargeRemaining)|$($b.BatteryStatus)\" } else { 'none' }"
        )
        if out in ("", "none"):
            return None, False
        try:
            pct_s, status = out.split("|")
            return int(pct_s), status in ("2", "6")  # 2=AC, 6=charging
        except ValueError:
            return None, False
    if IS_LINUX:
        # upower — самый надёжный кроссдистрибутивный способ; fallback на /sys/class/power_supply.
        if _which("upower"):
            dev = _run(["upower", "-e"], timeout=3)
            bat_dev = next((line for line in dev.splitlines() if "battery" in line.lower()), None)
            if bat_dev:
                info = _run(["upower", "-i", bat_dev.strip()], timeout=3)
                pct, state_s = None, ""
                for line in info.splitlines():
                    line = line.strip()
                    if line.startswith("percentage:"):
                        try:
                            pct = int(line.split(":", 1)[1].strip().rstrip("%"))
                        except ValueError:
                            pass
                    elif line.startswith("state:"):
                        state_s = line.split(":", 1)[1].strip()
                if pct is not None:
                    return pct, state_s in ("charging", "fully-charged")
        try:
            base = Path("/sys/class/power_supply")
            for entry in base.glob("BAT*"):
                pct = int((entry / "capacity").read_text(encoding="utf-8").strip())
                status = (entry / "status").read_text(encoding="utf-8").strip().lower()
                return pct, status == "charging"
        except (OSError, ValueError):
            pass
        return None, False
    return None, False


# ══════════════════════════════ активное приложение ═════════════════════════

def frontmost_app() -> str:
    if IS_MAC:
        return _run(
            ["osascript", "-e", 'tell application "System Events" to get name of first application process whose frontmost is true'],
            timeout=3,
        ).strip()
    if IS_WINDOWS:
        return _powershell(
            "Add-Type -Namespace W -Name U -MemberDefinition '"
            "[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();"
            "[DllImport(\"user32.dll\")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);'; "
            "$h=[W.U]::GetForegroundWindow(); $pid=0; [W.U]::GetWindowThreadProcessId($h,[ref]$pid) | Out-Null; "
            "(Get-Process -Id $pid -ErrorAction SilentlyContinue).ProcessName",
            timeout=3,
        )
    if IS_LINUX:
        # X11: xdotool/wmctrl читают активное окно. На чистом Wayland (без совместимого протокола)
        # это недоступно — большинство композиторов не дают такого доступа сторонним процессам.
        if _which("xdotool"):
            wid = _run(["xdotool", "getactivewindow"], timeout=2).strip()
            if wid:
                name = _run(["xdotool", "getwindowclassname", wid], timeout=2).strip()
                if name:
                    return name
                return _run(["xdotool", "getwindowname", wid], timeout=2).strip()
        if _which("wmctrl"):
            out = _run(["wmctrl", "-a", ":ACTIVE:", "-v"], timeout=2)
            if out:
                return out.strip().splitlines()[-1]
        return ""
    return ""


# ══════════════════════════════ уведомления/звук ════════════════════════════

def notify(title: str, text: str) -> None:
    try:
        if IS_MAC:
            subprocess.run(["osascript", "-e", f'display notification "{text}" with title "{title}" sound name "Glass"'], timeout=5)
        elif IS_WINDOWS:
            esc_t = title.replace("'", "''")
            esc_m = text.replace("'", "''")
            subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                 "Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
                 "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                 f"$n.ShowBalloonTip(5000, '{esc_t}', '{esc_m}', [System.Windows.Forms.ToolTipIcon]::Info); "
                 "Start-Sleep -Seconds 5; $n.Dispose()"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        elif IS_LINUX:
            if _which("notify-send"):
                subprocess.Popen(["notify-send", "-a", "JARVIS", title, text])
    except Exception:
        pass


def play_timer_sound() -> None:
    try:
        if IS_MAC:
            subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
        elif IS_WINDOWS:
            subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                 "[System.Media.SystemSounds]::Asterisk.Play(); Start-Sleep -Milliseconds 400"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        elif IS_LINUX:
            sound = "/usr/share/sounds/freedesktop/stereo/complete.oga"
            if _which("paplay") and Path(sound).exists():
                subprocess.Popen(["paplay", sound])
            elif _which("canberra-gtk-play"):
                subprocess.Popen(["canberra-gtk-play", "-i", "complete"])
            elif _which("aplay") and Path(sound).exists():
                subprocess.Popen(["aplay", sound])
    except Exception:
        pass


# ══════════════════════════════ скриншот контекста экрана ═══════════════════

def capture_screen(out_dir: Path) -> str | None:
    """Скриншот активного дисплея — тот же каталог, что у mac_screenshot/win_screenshot."""
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"context-{dt.datetime.now():%Y%m%d-%H%M%S}.png"
        if IS_MAC:
            subprocess.run(["screencapture", "-x", str(path)], timeout=10, capture_output=True)
        elif IS_WINDOWS:
            script = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
                "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
                "$g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size); "
                f"$bmp.Save('{path}', [System.Drawing.Imaging.ImageFormat]::Png)"
            )
            _powershell(script, timeout=15)
        elif IS_LINUX:
            if _which("grim"):  # Wayland (wlroots-совместимые композиторы: Sway, Hyprland...)
                subprocess.run(["grim", str(path)], timeout=10, capture_output=True)
            elif _which("gnome-screenshot"):
                subprocess.run(["gnome-screenshot", "-f", str(path)], timeout=10, capture_output=True)
            elif _which("spectacle"):  # KDE
                subprocess.run(["spectacle", "-b", "-n", "-o", str(path)], timeout=10, capture_output=True)
            elif _which("scrot"):  # X11
                subprocess.run(["scrot", "-o", str(path)], timeout=10, capture_output=True)
            elif _which("import"):  # ImageMagick, X11
                subprocess.run(["import", "-window", "root", str(path)], timeout=10, capture_output=True)
            else:
                return None
        else:
            return None
        return str(path) if path.exists() else None
    except Exception:
        return None


# ══════════════════════════════ фоновые команды (Shortcuts / .ps1) ══════════

def run_shortcut(name: str) -> bool:
    """Запустить именованную автоматизацию, если она есть. Никогда не бросает.

    macOS: Быстрая команда (Shortcuts.app). Windows: скрипт $HERMES_HOME/jarvis/shortcuts/<name>.ps1|.bat
    """
    try:
        if IS_MAC:
            proc = subprocess.run(["shortcuts", "run", name], capture_output=True, timeout=15)
            return proc.returncode == 0
        if IS_WINDOWS:
            import os
            home = Path(os.environ.get("HERMES_HOME") or (Path(os.environ.get("LOCALAPPDATA", "")) / "hermes")).expanduser()
            safe = "".join(c for c in name if c.isalnum() or c in " -_")
            for ext, runner in ((".ps1", ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]), (".bat", [])):
                script = home / "jarvis" / "shortcuts" / f"{safe}{ext}"
                if script.exists():
                    cmd = runner + [str(script)] if runner else [str(script)]
                    proc = subprocess.run(cmd, capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
                    return proc.returncode == 0
            return False
        if IS_LINUX:
            home = Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()
            safe = "".join(c for c in name if c.isalnum() or c in " -_")
            for ext in (".sh", ".py"):
                script = home / "jarvis" / "shortcuts" / f"{safe}{ext}"
                if script.exists():
                    cmd = ["bash", str(script)] if ext == ".sh" else [sys.executable, str(script)]
                    proc = subprocess.run(cmd, capture_output=True, timeout=15)
                    return proc.returncode == 0
            return False
    except Exception:
        return False
    return False


# ══════════════════════════════ режим "не беспокоить" ═══════════════════════

FOCUS_MAP = {"do not disturb": "focus", "не беспокоить": "focus", "work": "focus", "работа": "focus",
             "sleep": "night", "сон": "night", "personal": "normal", "личное": "normal", "": "normal"}


def map_focus(focus_name: str) -> str | None:
    return FOCUS_MAP.get((focus_name or "").strip().lower())


def current_focus() -> str | None:
    """Имя активного режима "не беспокоить" ('' — нет); None — недоступно на этой платформе.

    Windows не предоставляет надёжный публичный API для статуса Focus Assist из PowerShell —
    честно возвращаем None (watchdog просто не будет синхронизировать режим на Windows).
    На Linux пробуем `gsettings` (GNOME: org.gnome.desktop.notifications show-banners) — это
    единственный распространённый кроссдистрибутивный сигнал "не беспокоить"; на других
    окружениях (KDE, Sway…) честно возвращаем None.
    На macOS читаем ~/Library/DoNotDisturb/DB напрямую (без предварительной проверки IS_MAC —
    так поведение остаётся тестируемым директориями на любой ОС, как в исходной реализации).
    """
    if IS_WINDOWS:
        return None
    if IS_LINUX and _which("gsettings"):
        out = _run(["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"], timeout=3).strip()
        if out != "":
            return "focus" if out == "false" else ""
    # Fallback (и путь исполнения в тестах на любой ОС): формат macOS DoNotDisturb DB,
    # каталог берётся через Path.home() — на не-macOS обычно просто не существует → None.
    base = Path.home() / "Library" / "DoNotDisturb" / "DB"
    try:
        assertions = json.loads((base / "Assertions.json").read_text(encoding="utf-8"))
        records = (assertions.get("data") or [{}])[0].get("storeAssertionRecords") or []
        if not records:
            return ""
        rec = max(records, key=lambda r: r.get("assertionStartDateTimestamp", 0))
        mode_id = rec.get("assertionDetails", {}).get("assertionDetailsModeIdentifier", "")
        configs = json.loads((base / "ModeConfigurations.json").read_text(encoding="utf-8"))
        modes = (configs.get("data") or [{}])[0].get("modeConfigurations") or {}
        mode = modes.get(mode_id, {}).get("mode", {})
        return mode.get("name") or mode_id.rsplit(".", 1)[-1] or ""
    except (OSError, ValueError, KeyError, IndexError):
        return None


# ══════════════════════════════ календарь (для watchdog "встреча скоро") ════

def upcoming_events(lead_min: int) -> list[dict]:
    """События, начинающиеся в ближайшие lead_min минут."""
    if IS_MAC:
        script = f'''
        set nowD to (current date)
        set endD to nowD + ({lead_min} * minutes)
        set output to ""
        tell application "Calendar"
            repeat with cal in calendars
                repeat with ev in (every event of cal whose start date \u2265 nowD and start date \u2264 endD)
                    set output to output & (summary of ev) & "|" & (time string of (start date of ev)) & linefeed
                end repeat
            end repeat
        end tell
        return output'''
        out = _run(["osascript", "-e", script], timeout=30)
        evs = []
        for line in out.splitlines():
            if "|" in line:
                t, st = line.split("|", 1)
                evs.append({"title": t.strip(), "start": st.strip()})
        return evs
    if IS_WINDOWS:
        # Раньше здесь был Outlook COM (New-Object -ComObject Outlook.Application) — убран:
        # 1) требовал установленный/настроенный MS Outlook (у большинства пользователей его нет —
        #    Gmail/Google Workspace/встроенная почта), поэтому события просто не показывались;
        #    2) первое обращение к COM-объекту Outlook в системе без запущенного профиля
        #    открывает мастер профиля/окно регистрации Outlook — этот вызов повторялся каждый
        #    watchdog-тик (по умолчанию раз в несколько минут), из-за чего окно всплывало
        #    непрерывно, даже когда watch_calendar не нужен пользователю с настроенным Outlook.
        # Кроссплатформенный источник — Google Calendar (jarvis-core/gcalendar.py), который
        # вызывающая сторона (Watchdog.upcoming_events) уже проверяет раньше этого fallback'а;
        # если он не настроен — календарных напоминаний на Windows просто не будет (безопасно).
        return []
    if IS_LINUX:
        # Нет единого системного календаря на Linux; поддерживаем khal (CLI поверх vdirsyncer/CalDAV),
        # если он установлен и настроен — иначе честно возвращаем пусто.
        if not _which("khal"):
            return []
        now = dt.datetime.now()
        end = now + dt.timedelta(minutes=lead_min)
        out = _run(["khal", "list", now.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")], timeout=10)
        evs = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith(("Mon ", "Tue ", "Wed ", "Thu ", "Fri ", "Sat ", "Sun ")):
                continue
            evs.append({"title": line, "start": ""})
        return evs
    return []


# ══════════════════════════════ бездействие пользователя ═══════════════════

def idle_seconds() -> float | None:
    """Секунды с последнего ввода. None — недоступно на этой платформе."""
    if IS_MAC:
        out = _run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], timeout=3)
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                try:
                    return int(line.rsplit("=", 1)[1].strip()) / 1e9
                except (ValueError, IndexError):
                    return None
        return None
    if IS_WINDOWS:
        out = _powershell(
            "Add-Type -Namespace W -Name I -MemberDefinition '"
            "[DllImport(\"user32.dll\")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO p);"
            "public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }"
            "'; $li = New-Object W.I+LASTINPUTINFO; $li.cbSize = [System.Runtime.InteropServices.Marshal]::SizeOf($li); "
            "[W.I]::GetLastInputInfo([ref]$li) | Out-Null; "
            "(([Environment]::TickCount - $li.dwTime) / 1000)"
        )
        try:
            return float(out)
        except ValueError:
            return None
    if IS_LINUX:
        # X11: xprintidle возвращает миллисекунды бездействия. На Wayland надёжного
        # кроссдесктопного API нет — возвращаем None.
        if _which("xprintidle"):
            out = _run(["xprintidle"], timeout=3).strip()
            try:
                return int(out) / 1000
            except ValueError:
                return None
        return None
    return None
