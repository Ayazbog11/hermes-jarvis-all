"""
Обработчики инструментов плагина jarvis-linux.

Контракт Hermes для обработчика:
    def handler(args: dict, **kwargs) -> str      # ВСЕГДА возвращает JSON-строку
    * не бросает исключений — все ошибки превращаются в {"success": false, "error": "..."}
    * принимает **kwargs (Hermes может передавать доп. контекст)

Каждый обработчик — тонкая обёртка над функциями из linux.py (аналог tools.py у
jarvis-macos/jarvis-windows, но вместо AppleScript/PowerShell — обычные утилиты
рабочего стола: wmctrl/xdotool, pactl/amixer, nmcli, bluetoothctl, upower, grim/scrot…).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path

from . import linux as lx
from .linux import LinuxError, json_err, json_ok, run, which

_SETTINGS = {
    "allow_raw_shell": False,
    "screenshot_dir": "",            # пусто → $HERMES_HOME/cache/jarvis/screenshots
    "default_player": "auto",
    "hud_url": "http://127.0.0.1:8765",
}


def configure(**settings) -> None:
    _SETTINGS.update({k: v for k, v in settings.items() if v is not None})


def guarded(fn):
    """Декоратор: проверка Linux + перевод исключений в JSON-ошибку."""

    def wrapper(args: dict | None = None, **kwargs) -> str:
        args = args or {}
        try:
            lx.require_linux()
            return fn(args)
        except LinuxError as e:
            return json_err(str(e))
        except Exception as e:  # обработчик не должен падать
            return json_err(f"{type(e).__name__}: {e}")

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ═══════════════════════════════ Приложения ════════════════════════════════

@guarded
def linux_app(args: dict) -> str:
    action = args.get("action")
    app = (args.get("app") or "").strip()

    if action == "list_running":
        return json_ok(apps=lx.running_apps(), frontmost=lx.frontmost_app())
    if not app:
        return json_err("Укажите имя приложения (app)")

    if action == "open":
        subprocess.Popen([app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          start_new_session=True)
        return json_ok(message=f"Открываю {app}")
    if action == "activate":
        if which("wmctrl"):
            run(["wmctrl", "-a", app], check=False)
            return json_ok(message=f"{app} на переднем плане")
        return json_err("Нужен wmctrl (sudo apt install wmctrl)")
    if action in ("quit", "force_quit"):
        sig = "-9" if action == "force_quit" else "-15"
        run(["pkill", sig, "-f", app], check=False)
        return json_ok(message=f"{app} {'принудительно завершён' if action == 'force_quit' else 'закрыт'}")
    if action == "hide":
        if which("xdotool"):
            wid = run(["xdotool", "search", "--class", app], check=False).splitlines()
            if wid:
                run(["xdotool", "windowminimize", wid[0]], check=False)
                return json_ok(message=f"{app} свёрнут")
            return json_err(f"Окно {app} не найдено")
        return json_err("Нужен xdotool для сворачивания окна")
    if action == "is_running":
        out = run(["pgrep", "-f", app], check=False)
        return json_ok(app=app, running=bool(out.strip()))
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_open(args: dict) -> str:
    target = lx.resolve_target(args.get("target", ""))
    if not target:
        return json_err("Укажите target")
    lx.open_target(target)
    return json_ok(opened=target)


@guarded
def linux_search(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return json_err("Пустой запрос")
    only_dir = str(Path(args["only_dir"]).expanduser()) if args.get("only_dir") else str(Path.home())
    limit = int(args.get("limit") or 20)
    pattern = query if "*" in query else f"*{query}*"
    if which("plocate") or which("locate"):
        binname = "plocate" if which("plocate") else "locate"
        out = run([binname, "-i", "--limit", str(limit), pattern], check=False)
        results = [line for line in lx.safe_list(out.splitlines()) if line.startswith(only_dir)] or lx.safe_list(out.splitlines())[:limit]
    else:
        out = run(["find", only_dir, "-iname", pattern, "-type", "f"], timeout=25, check=False)
        results = lx.safe_list(out.splitlines())[:limit]
    return json_ok(query=query, count=len(results), results=results)


@guarded
def linux_files(args: dict) -> str:
    action = args.get("action")
    if action == "reveal":
        p = str(Path(args.get("path", "~")).expanduser())
        if which("nautilus"):
            run(["nautilus", "--select", p], check=False)
        elif which("dolphin"):
            run(["dolphin", "--select", p], check=False)
        else:
            lx.open_target(str(Path(p).parent))
        return json_ok(revealed=p)
    if action == "new_window":
        p = str(Path(args.get("path", "~")).expanduser())
        lx.open_target(p)
        return json_ok(opened=p)
    if action == "open_trash":
        if which("nautilus"):
            run(["nautilus", "trash:///"], check=False)
        else:
            lx.open_target("trash:///")
        return json_ok(message="Корзина открыта")
    if action == "empty_trash":
        if which("gio"):
            run(["gio", "trash", "--empty"], check=False)
        elif which("trash-empty"):
            run(["trash-empty"], check=False)
        else:
            return json_err("Нужен gio (glib2) или trash-cli для очистки корзины")
        return json_ok(message="Корзина очищена")
    return json_err(f"Неизвестное действие: {action}")


# ═══════════════════════════════ Система ═══════════════════════════════════

@guarded
def linux_volume(args: dict) -> str:
    action = args.get("action")
    level = args.get("level")
    use_pactl = bool(which("pactl"))

    def current() -> int:
        if use_pactl:
            out = run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], check=False)
            for tok in out.split():
                if tok.endswith("%"):
                    return int(tok.rstrip("%"))
            return 0
        out = run(["amixer", "get", "Master"], check=False)
        for tok in out.split():
            if tok.startswith("[") and tok.endswith("%]"):
                return int(tok.strip("[]%"))
        return 0

    def muted() -> bool:
        if use_pactl:
            out = run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], check=False)
            return "yes" in out.lower()
        out = run(["amixer", "get", "Master"], check=False)
        return "[off]" in out.lower()

    if not use_pactl and not which("amixer"):
        return json_err("Нужен pactl (PipeWire/PulseAudio) или amixer (ALSA)")

    if action == "get":
        return json_ok(volume=current(), muted=muted())
    if action == "set":
        if level is None:
            return json_err("Для set нужен level 0–100")
        lv = max(0, min(100, int(level)))
        if use_pactl:
            run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{lv}%"], check=False)
        else:
            run(["amixer", "set", "Master", f"{lv}%"], check=False)
        return json_ok(volume=lv)
    if action in ("up", "down"):
        step = int(level or 10)
        lv = current() + (step if action == "up" else -step)
        lv = max(0, min(100, lv))
        if use_pactl:
            run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{lv}%"], check=False)
        else:
            run(["amixer", "set", "Master", f"{lv}%"], check=False)
        return json_ok(volume=lv)
    if action == "mute":
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"] if use_pactl else ["amixer", "set", "Master", "mute"], check=False)
        return json_ok(muted=True)
    if action == "unmute":
        run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"] if use_pactl else ["amixer", "set", "Master", "unmute"], check=False)
        return json_ok(muted=False)
    if action == "toggle_mute":
        m = not muted()
        if use_pactl:
            run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if m else "0"], check=False)
        else:
            run(["amixer", "set", "Master", "mute" if m else "unmute"], check=False)
        return json_ok(muted=m)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_brightness(args: dict) -> str:
    action = args.get("action")
    level = args.get("level")

    def current() -> int | None:
        if which("brightnessctl"):
            try:
                cur = int(run(["brightnessctl", "get"], check=False))
                mx = int(run(["brightnessctl", "max"], check=False))
                return round(cur / mx * 100) if mx else None
            except ValueError:
                return None
        if which("xbacklight"):
            try:
                return round(float(run(["xbacklight", "-get"], check=False)))
            except ValueError:
                return None
        return None

    if not which("brightnessctl") and not which("xbacklight"):
        return json_err("Нужен brightnessctl или xbacklight (sudo apt install brightnessctl)")

    if action == "get":
        cur = current()
        if cur is None:
            return json_err("Яркость недоступна на этом устройстве")
        return json_ok(brightness=cur)
    if action == "set":
        if level is None:
            return json_err("Для set нужен level 0–100")
        lv = max(0, min(100, int(level)))
        if which("brightnessctl"):
            run(["brightnessctl", "set", f"{lv}%"], check=False)
        else:
            run(["xbacklight", "-set", str(lv)], check=False)
        return json_ok(brightness=lv)
    if action in ("up", "down"):
        n = int(level or 10)
        if which("brightnessctl"):
            run(["brightnessctl", "set", f"{n}%{'+' if action == 'up' else '-'}"], check=False)
        else:
            run(["xbacklight", "-inc" if action == "up" else "-dec", str(n)], check=False)
        cur = current()
        return json_ok(brightness=cur if cur is not None else -1)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_dark_mode(args: dict) -> str:
    action = args.get("action")
    if not which("gsettings"):
        return json_err("Автоматическое переключение темы поддерживается только на GNOME/GTK (gsettings). На KDE переключите через Параметры системы → Внешний вид.")
    scheme_key = ("org.gnome.desktop.interface", "color-scheme")

    def is_dark() -> bool:
        out = run(["gsettings", "get", *scheme_key], check=False)
        return "dark" in out.lower()

    if action == "get":
        return json_ok(dark=is_dark())
    if action == "toggle":
        target = "default" if is_dark() else "prefer-dark"
    elif action == "on":
        target = "prefer-dark"
    elif action == "off":
        target = "default"
    else:
        return json_err(f"Неизвестное действие: {action}")
    run(["gsettings", "set", *scheme_key, target], check=False)
    return json_ok(dark=target == "prefer-dark")


@guarded
def linux_power(args: dict) -> str:
    action = args.get("action")
    confirmed = bool(args.get("confirmed"))
    dangerous = {"restart", "shutdown", "logout", "hibernate"}
    if action in dangerous and not confirmed:
        return json_err(f"Действие «{action}» требует явного подтверждения пользователя. Переспросите и передайте confirmed=true.")
    if action == "lock":
        if which("loginctl"):
            run(["loginctl", "lock-session"], check=False)
        elif which("xdg-screensaver"):
            run(["xdg-screensaver", "lock"], check=False)
        else:
            return json_err("Нужен loginctl (systemd-logind) или xdg-screensaver")
        return json_ok(message="Экран заблокирован")
    if action == "sleep":
        if which("systemctl"):
            run(["systemctl", "suspend"], check=False)
        else:
            return json_err("Нужен systemctl (systemd)")
        return json_ok(message="Засыпаю")
    if action == "hibernate":
        if which("systemctl"):
            run(["systemctl", "hibernate"], check=False)
            return json_ok(message="Гибернация…")
        return json_err("Нужен systemctl (systemd)")
    if action == "screensaver":
        if which("xdg-screensaver"):
            run(["xdg-screensaver", "activate"], check=False)
            return json_ok(message="Заставка запущена")
        return json_err("Нужен xdg-screensaver")
    if action == "restart":
        if which("systemctl"):
            run(["systemctl", "reboot"], check=False)
        else:
            return json_err("Нужен systemctl (systemd)")
        return json_ok(message="Перезагрузка…")
    if action == "shutdown":
        if which("systemctl"):
            run(["systemctl", "poweroff"], check=False)
        else:
            return json_err("Нужен systemctl (systemd)")
        return json_ok(message="Выключение…")
    if action == "logout":
        if which("loginctl"):
            sess = run(["loginctl", "show-session", "--property=Id", "--value"], check=False).strip() or None
            run(["loginctl", "terminate-session", sess] if sess else ["loginctl", "terminate-user", os.environ.get("USER", "")], check=False)
        else:
            return json_err("Нужен loginctl (systemd-logind)")
        return json_ok(message="Выход из системы…")
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_process(args: dict) -> str:
    action = args.get("action")
    if action == "list":
        by_memory = (args.get("sort_by") or "cpu") == "memory"
        limit = int(args.get("limit") or 12)
        sort_key = "-%mem" if by_memory else "-%cpu"
        out = run(["bash", "-c", f"ps -eo pid,pcpu,rss,comm --sort={sort_key} | tail -n +2 | head -{limit}"], check=False)
        procs = []
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                pid, cpu, rss_kb, name = parts
                try:
                    procs.append({"pid": int(pid), "name": name, "cpu_percent": float(cpu), "memory_mb": round(int(rss_kb) / 1024, 1)})
                except ValueError:
                    continue
        return json_ok(processes=procs, sorted_by=args.get("sort_by") or "cpu")
    if action == "find":
        name = (args.get("name") or "").strip()
        if not name:
            return json_err("Укажите name")
        out = run(["pgrep", "-fli", name], check=False)
        procs = []
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                procs.append({"pid": int(parts[0]), "name": parts[1]})
        return json_ok(query=name, count=len(procs), processes=procs)
    if action == "kill":
        if not args.get("confirmed"):
            return json_err("Завершение процесса требует явного подтверждения пользователя. Переспросите и передайте confirmed=true.")
        pid = args.get("pid")
        name = (args.get("name") or "").strip()
        if not pid and not name:
            return json_err("Укажите pid или name")
        sig = "-9" if args.get("force") else "-15"
        if pid:
            run(["kill", sig, str(int(pid))], check=False)
        else:
            run(["pkill", sig, "-f", name], check=False)
        return json_ok(killed=pid or name)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_wifi(args: dict) -> str:
    action = args.get("action")
    if not which("nmcli"):
        return json_err("Нужен NetworkManager (nmcli)")
    if action in ("on", "off"):
        run(["nmcli", "radio", "wifi", action], check=False)
        return json_ok(wifi=action)
    if action == "status":
        power = run(["nmcli", "radio", "wifi"], check=False).strip().lower()
        ssid = run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], check=False)
        network = ""
        for line in ssid.splitlines():
            if line.startswith("yes:"):
                network = line.split(":", 1)[1]
                break
        return json_ok(power="on" if power == "enabled" else "off", network=network)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_bluetooth(args: dict) -> str:
    action = args.get("action")
    if not which("bluetoothctl"):
        return json_err("Нужен bluetoothctl (пакет bluez)")
    # bluetoothctl show/power/devices обращается к bluetoothd через D-Bus и обычно отвечает
    # почти мгновенно; на машинах без работающего стека (нет адаптера/демона) команда может
    # висеть до истечения таймаута — используем короткий таймаут, чтобы не «замораживать» агента
    # на 30с (как это уже сделано для mac_bluetooth в оригинале через timeout=20).
    if action == "status":
        try:
            out = run(["bluetoothctl", "show"], timeout=8, check=False)
        except LinuxError as e:
            return json_err(f"bluetoothctl не отвечает: {e}")
        power = "on" if "Powered: yes" in out else "off"
        return json_ok(power=power)
    if action in ("on", "off"):
        try:
            run(["bluetoothctl", "power", "on" if action == "on" else "off"], timeout=8, check=False)
        except LinuxError as e:
            return json_err(f"bluetoothctl не отвечает: {e}")
        return json_ok(power=action)
    if action == "devices":
        try:
            out = run(["bluetoothctl", "devices", "Connected"], timeout=8, check=False)
        except LinuxError as e:
            return json_err(f"bluetoothctl не отвечает: {e}")
        devices = [line.split(" ", 2)[-1] for line in lx.safe_list(out.splitlines())]
        return json_ok(connected=devices)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_battery(args: dict) -> str:
    if which("upower"):
        devs = run(["upower", "-e"], check=False)
        bat_dev = next((line for line in devs.splitlines() if "battery" in line.lower()), None)
        if bat_dev:
            info = run(["upower", "-i", bat_dev.strip()], check=False)
            pct, state_s = None, "unknown"
            for line in info.splitlines():
                line = line.strip()
                if line.startswith("percentage:"):
                    try:
                        pct = int(line.split(":", 1)[1].strip().rstrip("%"))
                    except ValueError:
                        pass
                elif line.startswith("state:"):
                    state_s = line.split(":", 1)[1].strip()
            return json_ok(percent=pct, charging=state_s == "charging", on_ac=state_s in ("charging", "fully-charged"), raw=state_s)
    base = Path("/sys/class/power_supply")
    for entry in base.glob("BAT*"):
        try:
            pct = int((entry / "capacity").read_text(encoding="utf-8").strip())
            status = (entry / "status").read_text(encoding="utf-8").strip().lower()
            return json_ok(percent=pct, charging=status == "charging", on_ac=status in ("charging", "full"), raw=status)
        except (OSError, ValueError):
            continue
    return json_err("На этом устройстве не обнаружено батареи (настольный ПК?) или недоступен upower/sysfs")


@guarded
def linux_system_info(args: dict) -> str:
    section = args.get("section") or "all"
    data: dict = {}
    if section in ("all", "hardware"):
        data["distro"] = run(["bash", "-c", ". /etc/os-release 2>/dev/null; echo \"$PRETTY_NAME\""], check=False) or "?"
        data["kernel"] = run(["uname", "-r"], check=False)
        data["chip"] = run(["bash", "-c", "lscpu 2>/dev/null | grep 'Model name' | sed 's/Model name:\\s*//'"], check=False) or "?"
        data["cores"] = run(["nproc"], check=False)
    if section in ("all", "memory"):
        out = run(["free", "-m"], check=False)
        for line in out.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                total, used = int(parts[1]), int(parts[2])
                data["memory_total_gb"] = round(total / 1024, 1)
                data["memory_used_percent"] = round(used / total * 100, 1) if total else 0
    if section in ("all", "disk"):
        out = run(["df", "-h", "--output=target,avail,size", "-x", "tmpfs", "-x", "devtmpfs"], check=False)
        data["disk"] = lx.safe_list(out.splitlines()[1:])
    if section in ("all", "network"):
        data["local_ip"] = run(["bash", "-c", "hostname -I 2>/dev/null | awk '{print $1}'"], check=False)
        data["hostname"] = run(["hostname"], check=False)
    if section in ("all", "uptime"):
        data["uptime"] = run(["bash", "-c", "uptime -p 2>/dev/null"], check=False)
    if section in ("all", "processes"):
        out = run(["bash", "-c", "ps -eo comm,%cpu --sort=-%cpu | head -8 | tail -7"], check=False)
        data["top_cpu"] = lx.safe_list(out.splitlines())
    return json_ok(**data)


# ═══════════════════════════════ Медиа ═════════════════════════════════════

@guarded
def linux_media(args: dict) -> str:
    action = args.get("action")
    if not which("playerctl"):
        return json_err("Нужен playerctl (MPRIS) — sudo apt install playerctl")
    player = lx.detect_player(args.get("player") or _SETTINGS["default_player"])
    prefix = ["playerctl"] + (["-p", player] if player else [])

    if action in ("play", "toggle"):
        run(prefix + ["play-pause" if action == "toggle" else "play"], check=False)
        return json_ok(player=player or "auto", action=action)
    if action == "pause":
        run(prefix + ["pause"], check=False)
        return json_ok(player=player or "auto", action="pause")
    if action == "next":
        run(prefix + ["next"], check=False)
        return json_ok(player=player or "auto", action="next")
    if action == "previous":
        run(prefix + ["previous"], check=False)
        return json_ok(player=player or "auto", action="previous")
    if action == "now_playing":
        artist = run(prefix + ["metadata", "artist"], check=False)
        title = run(prefix + ["metadata", "title"], check=False)
        if not title:
            return json_ok(player=player or "unknown", state="unknown")
        return json_ok(player=player or "auto", track=title, artist=artist)
    return json_err(f"Неизвестное действие: {action}")


def _stop_speech() -> list[str]:
    """Остановить всё, что говорит вслух: TTS-процесс и попросить HUD заглушить озвучку браузера."""
    killed = []
    for name in ("espeak", "espeak-ng", "spd-say", "piper"):
        try:
            r = subprocess.run(["pkill", "-x", name], capture_output=True, timeout=3)
            if r.returncode == 0:
                killed.append(name)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import urllib.request
        urllib.request.urlopen(urllib.request.Request(_SETTINGS.get("hud_url", "http://127.0.0.1:8765") + "/api/hush",
                                                      data=b"{}", headers={"Content-Type": "application/json"}, method="POST"), timeout=1).close()
        killed.append("hud")
    except Exception:
        pass
    return killed


@guarded
def linux_say(args: dict) -> str:
    if args.get("action") == "stop":
        return json_ok(stopped=_stop_speech())
    text = args.get("text", "")
    if not text:
        return json_err("Пустой текст")
    _stop_speech()
    voice = args.get("voice")
    if which("espeak-ng"):
        cmd = ["espeak-ng"] + (["-v", voice] if voice else ["-v", "ru"]) + [text]
    elif which("espeak"):
        cmd = ["espeak"] + (["-v", voice] if voice else ["-v", "ru"]) + [text]
    elif which("spd-say"):
        cmd = ["spd-say"] + (["-y", voice] if voice else []) + [text]
    else:
        return json_err("Нужен espeak-ng, espeak или speech-dispatcher (spd-say)")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json_ok(spoken=text)


@guarded
def linux_notify(args: dict) -> str:
    title, msg = args.get("title", "JARVIS"), args.get("message", "")
    urgency = args.get("urgency", "normal")
    if not which("notify-send"):
        return json_err("Нужен notify-send (пакет libnotify-bin)")
    run(["notify-send", "-a", "JARVIS", "-u", urgency, title, msg], check=False)
    return json_ok(shown=True)


@guarded
def linux_screenshot(args: dict) -> str:
    out_dir = Path(_SETTINGS["screenshot_dir"]).expanduser() if _SETTINGS.get("screenshot_dir") else lx.cache_dir("screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / lx.stamp("screen", "png")
    mode = args.get("mode") or "screen"

    if lx.IS_WAYLAND and which("grim"):
        if mode == "front_window" and which("slurp"):
            geom = run(["bash", "-c", "slurp -w 0 2>/dev/null || true"], check=False)
            run(["grim"] + (["-g", geom] if geom else []) + [str(path)], timeout=10, check=False)
        else:
            run(["grim", str(path)], timeout=10, check=False)
    elif which("gnome-screenshot"):
        flag = "-w" if mode == "front_window" else "-f"
        run(["gnome-screenshot", flag, str(path)] if flag == "-f" else ["gnome-screenshot", "-w", "-f", str(path)], timeout=10, check=False)
    elif which("spectacle"):
        run(["spectacle", "-b", "-n", ("-a" if mode == "front_window" else "-f"), "-o", str(path)], timeout=10, check=False)
    elif which("scrot"):
        run(["scrot", "-u", "-o", str(path)] if mode == "front_window" else ["scrot", "-o", str(path)], timeout=10, check=False)
    elif which("import"):
        run(["import", "-window", "root", str(path)], timeout=10, check=False)
    else:
        return json_err("Нужен grim (Wayland) или scrot/gnome-screenshot/spectacle/import (X11) для скриншотов")

    if not path.exists():
        return json_err("Скриншот не создан")
    return json_ok(path=str(path), hint="Передайте path в vision_analyze, чтобы описать содержимое экрана")


@guarded
def linux_camera_snap(args: dict) -> str:
    if not which("ffmpeg"):
        return json_err("Нужен ffmpeg для снимка с камеры")
    device = args.get("device") or "/dev/video0"
    out_dir = lx.cache_dir("camera")
    path = out_dir / lx.stamp("cam", "jpg")
    warmup = float(args.get("warmup") or 1.0)
    run(["ffmpeg", "-y", "-f", "v4l2", "-i", device, "-frames:v", "1", str(path)], timeout=int(10 + warmup), check=False)
    if not path.exists():
        return json_err(f"Не удалось получить снимок с камеры {device}")
    return json_ok(path=str(path), hint="Передайте path в vision_analyze")


@guarded
def linux_wallpaper(args: dict) -> str:
    p = Path(args.get("path", "")).expanduser()
    if not p.exists():
        return json_err(f"Файл не найден: {p}")
    if which("gsettings"):
        uri = f"file://{p}"
        run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri], check=False)
        run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", uri], check=False)
        return json_ok(wallpaper=str(p))
    if which("plasma-apply-wallpaperimage"):
        run(["plasma-apply-wallpaperimage", str(p)], check=False)
        return json_ok(wallpaper=str(p))
    return json_err("Автоматическая смена обоев поддерживается на GNOME (gsettings) и KDE Plasma (plasma-apply-wallpaperimage); на других DE смените вручную.")


# ═══════════════════════════════ Продуктивность ════════════════════════════

def _khal_available() -> bool:
    return bool(which("khal"))


@guarded
def linux_calendar(args: dict) -> str:
    action = args.get("action")
    today = dt.date.today()
    if not _khal_available():
        return json_err("khal не установлен/не настроен (CLI-календарь поверх CalDAV). Установите: pip install khal, либо используйте linux_reminders для локальных напоминаний.")
    if action in ("today", "tomorrow", "on_date"):
        d = today if action == "today" else (today + dt.timedelta(days=1) if action == "tomorrow" else dt.date.fromisoformat(args["date"]))
        out = run(["khal", "list", d.strftime("%Y-%m-%d"), (d + dt.timedelta(days=1)).strftime("%Y-%m-%d")], check=False)
        events = [line.strip() for line in out.splitlines() if line.strip() and not line.strip().startswith(("Mon ", "Tue ", "Wed ", "Thu ", "Fri ", "Sat ", "Sun "))]
        return json_ok(date=str(d), events=events)
    if action == "create":
        title = args.get("title") or "Событие"
        d = dt.date.fromisoformat(args.get("date") or str(today))
        start_time = args.get("start_time") or "12:00"
        dur = int(args.get("duration_min") or 60)
        out = run(["khal", "new", d.strftime("%Y-%m-%d"), start_time, f"{dur}m", title], check=False)
        return json_ok(created=title, date=str(d), start=start_time, duration_min=dur, khal_output=out)
    return json_err(f"Неизвестное действие: {action}")


def _reminders_file() -> Path:
    p = lx.hermes_home() / "jarvis" / "reminders.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("[]", encoding="utf-8")
    return p


@guarded
def linux_reminders(args: dict) -> str:
    """Простые локальные напоминания (JSON) — кроссплатформенный аналог macOS Reminders.app."""
    action = args.get("action")
    p = _reminders_file()
    items = json.loads(p.read_text(encoding="utf-8"))
    list_name = args.get("list_name") or "default"
    if action == "list":
        active = [i["title"] for i in items if not i.get("done") and i.get("list", "default") == list_name]
        return json_ok(reminders=active)
    if action == "add":
        title = args.get("title")
        if not title:
            return json_err("Нужен title")
        items.append({"title": title, "due": args.get("due"), "list": list_name, "done": False, "created": dt.datetime.now().isoformat()})
        p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return json_ok(added=title, due=args.get("due"))
    if action == "complete":
        title = (args.get("title") or "").lower()
        found = False
        for i in items:
            if not i.get("done") and title in i["title"].lower():
                i["done"] = True
                found = True
                break
        p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return json_ok(completed=args.get("title"), found=found)
    return json_err(f"Неизвестное действие: {action}")


def _notes_dir() -> Path:
    p = lx.hermes_home() / "jarvis" / "notes"
    p.mkdir(parents=True, exist_ok=True)
    return p


@guarded
def linux_notes(args: dict) -> str:
    """Заметки-файлы .md — простой кроссплатформенный аналог Apple Notes."""
    action = args.get("action")
    base = _notes_dir() / (args.get("folder") or "")
    base.mkdir(parents=True, exist_ok=True)
    if action == "create":
        title = args.get("title") or f"JARVIS {time.strftime('%d.%m.%Y %H:%M')}"
        body = args.get("body") or ""
        safe_name = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:80] or "note"
        path = base / f"{safe_name}.md"
        path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        return json_ok(created=title, path=str(path))
    if action == "search":
        q = (args.get("query") or "").lower()
        found = []
        for f in _notes_dir().rglob("*.md"):
            try:
                if q in f.stem.lower() or q in f.read_text(encoding="utf-8", errors="ignore").lower():
                    found.append(f.stem)
            except OSError:
                continue
        return json_ok(query=args.get("query"), notes=found)
    if action == "read":
        t = (args.get("title") or "").lower()
        for f in _notes_dir().rglob("*.md"):
            if t in f.stem.lower():
                return json_ok(title=f.stem, text=f.read_text(encoding="utf-8", errors="ignore"))
        return json_err("Заметка не найдена")
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_clipboard(args: dict) -> str:
    if args.get("action") == "get":
        return json_ok(text=lx.clipboard_get())
    if args.get("action") == "set":
        lx.clipboard_set(args.get("text") or "")
        return json_ok(copied=True)
    return json_err("action должен быть get или set")


@guarded
def linux_type(args: dict) -> str:
    action = args.get("action")
    text = args.get("text", "")
    if action == "type_text":
        lx.type_text(text)
        return json_ok(typed=len(text))
    if action == "keystroke":
        mods_map = {"ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift", "super": "super", "win": "super"}
        mods = []
        for m in args.get("modifiers") or []:
            key = str(m).lower()
            if key not in mods_map:
                return json_err(f"Неизвестный модификатор {m!r}; допустимы: ctrl, alt, shift, super")
            mods.append(mods_map[key])
        combo = "+".join(mods + [text])
        lx.send_keystroke(combo)
        return json_ok(pressed=text, modifiers=mods)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_window(args: dict) -> str:
    action = args.get("action")
    app = args.get("app")
    if not which("wmctrl"):
        return json_err("Нужен wmctrl (sudo apt install wmctrl)")
    if action == "list":
        out = run(["wmctrl", "-l"], check=False)
        windows = [" ".join(line.split()[3:]) for line in lx.safe_list(out.splitlines())]
        return json_ok(app=app or "*", windows=windows)

    def target_flag() -> list[str]:
        return ["-a", app] if app else ["-r", ":ACTIVE:"]

    if action == "minimize":
        if which("xdotool"):
            wid = run(["xdotool", "getactivewindow"] if not app else ["xdotool", "search", "--class", app], check=False).splitlines()
            if wid:
                run(["xdotool", "windowminimize", wid[0]], check=False)
        return json_ok(app=app or "(активное)", action=action)
    if action == "maximize":
        run(["wmctrl"] + target_flag() + ["-b", "add,maximized_vert,maximized_horz"], check=False)
        return json_ok(app=app or "(активное)", action=action)
    if action in ("left_half", "right_half", "center") and which("xdotool"):
        geo = run(["xdotool", "getdisplaygeometry"], check=False).split()
        w, h = (int(geo[0]), int(geo[1])) if len(geo) == 2 else (1920, 1080)
        wid = run(["xdotool", "getactivewindow"] if not app else ["xdotool", "search", "--class", app], check=False).splitlines()
        if not wid:
            return json_err("Окно не найдено")
        wid = wid[0]
        run(["xdotool", "windowsize", wid, str(w // 2), str(h)], check=False)
        if action == "left_half":
            run(["xdotool", "windowmove", wid, "0", "0"], check=False)
        elif action == "right_half":
            run(["xdotool", "windowmove", wid, str(w // 2), "0"], check=False)
        else:
            cw, ch = int(w * 0.7), int(h * 0.7)
            run(["xdotool", "windowsize", wid, str(cw), str(ch)], check=False)
            run(["xdotool", "windowmove", wid, str((w - cw) // 2), str((h - ch) // 2)], check=False)
        return json_ok(app=app or "(активное)", action=action)
    if action in ("left_half", "right_half", "center"):
        return json_err("Для перемещения окон нужен xdotool (sudo apt install xdotool)")
    return json_err(f"Неизвестное действие: {action}")


def _shortcuts_dir() -> Path:
    p = lx.hermes_home() / "jarvis" / "shortcuts"
    p.mkdir(parents=True, exist_ok=True)
    return p


@guarded
def linux_shortcut(args: dict) -> str:
    action = args.get("action") or "run"
    d = _shortcuts_dir()
    if action == "list":
        names = sorted({f.stem for f in d.glob("*.sh")} | {f.stem for f in d.glob("*.py")})
        return json_ok(shortcuts=names)
    name = args.get("name")
    if not name:
        return json_err("Нужно имя команды (name)")
    sh = d / f"{name}.sh"
    py = d / f"{name}.py"
    inp = args.get("input") or ""
    if sh.exists():
        proc = subprocess.run(["bash", str(sh), inp], capture_output=True, timeout=120, text=True, encoding="utf-8", errors="replace")
    elif py.exists():
        import sys as _sys
        proc = subprocess.run([_sys.executable, str(py), inp], capture_output=True, timeout=120, text=True, encoding="utf-8", errors="replace")
    else:
        return json_err(f"Скрипт не найден: {d}/{name}.sh|.py")
    if proc.returncode != 0:
        return json_err((proc.stderr or "").strip() or f"Код {proc.returncode}")
    return json_ok(ran=name, output=(proc.stdout or "").strip())


@guarded
def linux_focus(args: dict) -> str:
    """DND через gsettings (GNOME) — на других окружениях честно сообщаем об ограничении."""
    action = args.get("action") or "get"
    if not which("gsettings"):
        return json_err("Автоматическое переключение «Не беспокоить» поддерживается только на GNOME (gsettings).")
    key = ("org.gnome.desktop.notifications", "show-banners")
    if action == "get":
        out = run(["gsettings", "get", *key], check=False).strip()
        active = out == "false"
        return json_ok(focus="focus" if active else "", active=active)
    if action == "set":
        name = (args.get("name") or "").strip().lower()
        if name not in ("on", "off"):
            return json_err("Нужно name: on | off")
        run(["gsettings", "set", *key, "false" if name == "on" else "true"], check=False)
        return json_ok(active=name == "on")
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_file_manage(args: dict) -> str:
    """Файловые операции «по-линуксовому»: удаление только в Корзину (freedesktop trash)."""
    action = args.get("action")
    src = Path(lx.resolve_target(args.get("path", ""))) if args.get("path") else None
    if action == "trash":
        if not src or not src.exists():
            return json_err("Файл не найден")
        if which("gio"):
            run(["gio", "trash", str(src)], check=False)
        elif which("trash-put"):
            run(["trash-put", str(src)], check=False)
        else:
            return json_err("Нужен gio (glib2) или trash-cli для перемещения в Корзину")
        return json_ok(trashed=str(src))
    if action == "rename":
        new_name = args.get("new_name", "").strip()
        if not src or not src.exists() or not new_name or "/" in new_name:
            return json_err("Нужны существующий path и new_name без «/»")
        dst = src.with_name(new_name)
        if dst.exists():
            return json_err(f"Уже существует: {dst}")
        src.rename(dst)
        return json_ok(renamed=str(dst))
    if action == "move":
        dst_dir = Path(lx.resolve_target(args.get("destination", "")))
        if not src or not src.exists() or not dst_dir.is_dir():
            return json_err("Нужны существующий path и папка destination")
        dst = dst_dir / src.name
        if dst.exists():
            return json_err(f"Уже существует: {dst}")
        src.rename(dst)
        return json_ok(moved=str(dst))
    if action == "mkdir":
        if not src:
            return json_err("Нужен path")
        src.mkdir(parents=True, exist_ok=True)
        return json_ok(created=str(src))
    if action == "list":
        d = src or Path.home()
        if not d.is_dir():
            return json_err("Не папка")
        items = sorted(d.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[: int(args.get("limit") or 30)]
        return json_ok(path=str(d), items=[{"name": p.name, "dir": p.is_dir(), "kb": round(p.stat().st_size / 1024, 1)} for p in items])
    if action == "info":
        if not src or not src.exists():
            return json_err("Файл не найден")
        st = src.stat()
        return json_ok(path=str(src), size_kb=round(st.st_size / 1024, 1), modified=dt.datetime.fromtimestamp(st.st_mtime).isoformat(), is_dir=src.is_dir())
    return json_err(f"Неизвестное действие: {action}")


@guarded
def linux_shell(args: dict) -> str:
    if not _SETTINGS.get("allow_raw_shell"):
        return json_err(
            "Выполнение произвольных команд отключено. Включите в config.yaml Hermes: "
            "plugins.entries.jarvis-linux.settings.allow_raw_shell: true"
        )
    out = run(["bash", "-c", args.get("script", "")], timeout=120, check=True)
    return json_ok(output=out)


# ─────────────────────────── таблица «имя → обработчик» ────────────────────

HANDLERS = {
    "linux_app": linux_app,
    "linux_open": linux_open,
    "linux_search": linux_search,
    "linux_files": linux_files,
    "linux_volume": linux_volume,
    "linux_brightness": linux_brightness,
    "linux_dark_mode": linux_dark_mode,
    "linux_power": linux_power,
    "linux_process": linux_process,
    "linux_wifi": linux_wifi,
    "linux_bluetooth": linux_bluetooth,
    "linux_battery": linux_battery,
    "linux_system_info": linux_system_info,
    "linux_media": linux_media,
    "linux_say": linux_say,
    "linux_notify": linux_notify,
    "linux_screenshot": linux_screenshot,
    "linux_camera_snap": linux_camera_snap,
    "linux_wallpaper": linux_wallpaper,
    "linux_calendar": linux_calendar,
    "linux_reminders": linux_reminders,
    "linux_notes": linux_notes,
    "linux_clipboard": linux_clipboard,
    "linux_type": linux_type,
    "linux_window": linux_window,
    "linux_shortcut": linux_shortcut,
    "linux_file_manage": linux_file_manage,
    "linux_focus": linux_focus,
    "linux_shell": linux_shell,
}
