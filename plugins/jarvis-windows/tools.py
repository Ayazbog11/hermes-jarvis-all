"""
Обработчики инструментов плагина jarvis-windows.

Контракт Hermes для обработчика:
    def handler(args: dict, **kwargs) -> str      # ВСЕГДА возвращает JSON-строку
    * не бросает исключений — все ошибки превращаются в {"success": false, "error": "..."}
    * принимает **kwargs (Hermes может передавать доп. контекст)

Каждый обработчик — тонкая обёртка над функциями из win.py (аналог tools.py у jarvis-macos,
но вместо AppleScript используется PowerShell / WMI / SendKeys / реестр).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path

from . import win
from .win import WinError, as_ps, json_err, json_ok, powershell, run, which

_SETTINGS = {
    "allow_raw_powershell": False,
    "screenshot_dir": "",            # пусто → %HERMES_HOME%\cache\jarvis\screenshots
    "default_player": "auto",
    "hud_url": "http://127.0.0.1:8765",
}


def configure(**settings) -> None:
    _SETTINGS.update({k: v for k, v in settings.items() if v is not None})


def guarded(fn):
    """Декоратор: проверка Windows + перевод исключений в JSON-ошибку."""

    def wrapper(args: dict | None = None, **kwargs) -> str:
        args = args or {}
        try:
            win.require_windows()
            return fn(args)
        except WinError as e:
            return json_err(str(e))
        except Exception as e:  # обработчик не должен падать
            return json_err(f"{type(e).__name__}: {e}")

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ═══════════════════════════════ Приложения ════════════════════════════════

@guarded
def win_app(args: dict) -> str:
    action = args.get("action")
    app = (args.get("app") or "").strip()

    if action == "list_running":
        return json_ok(apps=win.running_apps(), frontmost=win.frontmost_app())
    if not app:
        return json_err("Укажите имя приложения (app)")

    if action == "open":
        run(["cmd", "/c", "start", "", app], check=False)
        return json_ok(message=f"Открываю {app}")
    if action == "activate":
        powershell(f"(New-Object -ComObject WScript.Shell).AppActivate({as_ps(app)}) | Out-Null")
        return json_ok(message=f"{app} на переднем плане")
    if action == "quit":
        run(["taskkill", "/IM", f"{app}.exe"], check=False)
        return json_ok(message=f"{app} закрыт")
    if action == "force_quit":
        run(["taskkill", "/F", "/IM", f"{app}.exe"], check=False)
        return json_ok(message=f"{app} принудительно завершён")
    if action == "hide":
        powershell(
            "Add-Type -Namespace W -Name U -MemberDefinition '"
            "[DllImport(\"user32.dll\")] public static extern bool ShowWindowAsync(IntPtr h, int n);'; "
            f"$p = Get-Process -Name {as_ps(app)} -ErrorAction SilentlyContinue | Select-Object -First 1; "
            "if ($p) { [W.U]::ShowWindowAsync($p.MainWindowHandle, 6) | Out-Null }"
        )
        return json_ok(message=f"{app} свёрнут")
    if action == "is_running":
        out = run(["tasklist", "/FI", f"IMAGENAME eq {app}.exe"], check=False)
        running = app.lower() + ".exe" in out.lower()
        return json_ok(app=app, running=running)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def win_open(args: dict) -> str:
    target = win.resolve_target(args.get("target", ""))
    if not target:
        return json_err("Укажите target")
    if args.get("app"):
        run(["cmd", "/c", "start", "", args["app"], target], check=False)
    else:
        run(["cmd", "/c", "start", "", target], check=False)
    return json_ok(opened=target)


@guarded
def win_search(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return json_err("Пустой запрос")
    only_dir = str(Path(args["only_dir"]).expanduser()) if args.get("only_dir") else str(Path.home())
    limit = int(args.get("limit") or 20)
    pattern = query if "*" in query else f"*{query}*"
    out = powershell(
        f"Get-ChildItem -Path {as_ps(only_dir)} -Recurse -Filter {as_ps(pattern)} -ErrorAction SilentlyContinue "
        f"-File | Select-Object -First {limit} -ExpandProperty FullName",
        timeout=25, check=False,
    )
    results = win.safe_list(out.splitlines())
    return json_ok(query=query, count=len(results), results=results)


@guarded
def win_explorer(args: dict) -> str:
    action = args.get("action")
    if action == "reveal":
        p = str(Path(args.get("path", "~")).expanduser())
        run(["explorer.exe", "/select,", p], check=False)
        return json_ok(revealed=p)
    if action == "new_window":
        p = str(Path(args.get("path", "~")).expanduser())
        run(["explorer.exe", p], check=False)
        return json_ok(opened=p)
    if action == "open_trash":
        run(["explorer.exe", "shell:RecycleBinFolder"], check=False)
        return json_ok(message="Корзина открыта")
    if action == "empty_trash":
        powershell("Clear-RecycleBin -Force -ErrorAction SilentlyContinue")
        return json_ok(message="Корзина очищена")
    return json_err(f"Неизвестное действие: {action}")


# ═══════════════════════════════ Система ═══════════════════════════════════

_VOL_HELPER = (
    "Add-Type -TypeDefinition @'\n"
    "using System.Runtime.InteropServices;\n"
    "[Guid(\"5CDF2C82-841E-4546-9722-0CF74078229A\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
    "interface IAudioEndpointVolume {\n"
    "  int f(); int g(); int h(); int i();\n"
    "  int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);\n"
    "  int j();\n"
    "  int GetMasterVolumeLevelScalar(out float pfLevel);\n"
    "  int k(); int l(); int m(); int n();\n"
    "  int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, System.Guid pguidEventContext);\n"
    "  int GetMute(out bool pbMute);\n"
    "}\n"
    "[Guid(\"D666063F-1587-4E43-81F1-B948E807363F\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
    "interface IMMDevice { int Activate(ref System.Guid id, int clsCtx, System.IntPtr activationParams, out IAudioEndpointVolume aev); }\n"
    "[Guid(\"A95664D2-9614-4F35-A746-DE8DB63617E6\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
    "interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint); }\n"
    "[ComImport, Guid(\"BCDE0395-E52F-467C-8E3D-C4579291692E\")] class MMDeviceEnumeratorComObject { }\n"
    "public static class Audio {\n"
    "  static IAudioEndpointVolume Vol() {\n"
    "    var en = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;\n"
    "    IMMDevice dev; en.GetDefaultAudioEndpoint(0, 1, out dev);\n"
    "    IAudioEndpointVolume aev; var iid = typeof(IAudioEndpointVolume).GUID;\n"
    "    dev.Activate(ref iid, 23, System.IntPtr.Zero, out aev);\n"
    "    return aev;\n"
    "  }\n"
    "  public static float Get() { float v; Vol().GetMasterVolumeLevelScalar(out v); return v; }\n"
    "  public static void Set(float v) { Vol().SetMasterVolumeLevelScalar(v, System.Guid.Empty); }\n"
    "  public static bool GetMute() { bool m; Vol().GetMute(out m); return m; }\n"
    "  public static void SetMute(bool m) { Vol().SetMute(m, System.Guid.Empty); }\n"
    "}\n"
    "'@ -ErrorAction SilentlyContinue; "
)


@guarded
def win_volume(args: dict) -> str:
    action = args.get("action")
    level = args.get("level")

    def current() -> int:
        return round(float(powershell(_VOL_HELPER + "[Audio]::Get()")) * 100)

    def muted() -> bool:
        return powershell(_VOL_HELPER + "[Audio]::GetMute()").strip().lower() == "true"

    if action == "get":
        return json_ok(volume=current(), muted=muted())
    if action == "set":
        if level is None:
            return json_err("Для set нужен level 0–100")
        lv = max(0, min(100, int(level)))
        powershell(_VOL_HELPER + f"[Audio]::Set({lv / 100})")
        return json_ok(volume=lv)
    if action in ("up", "down"):
        step = int(level or 10)
        lv = current() + (step if action == "up" else -step)
        lv = max(0, min(100, lv))
        powershell(_VOL_HELPER + f"[Audio]::Set({lv / 100})")
        return json_ok(volume=lv)
    if action == "mute":
        powershell(_VOL_HELPER + "[Audio]::SetMute($true)")
        return json_ok(muted=True)
    if action == "unmute":
        powershell(_VOL_HELPER + "[Audio]::SetMute($false)")
        return json_ok(muted=False)
    if action == "toggle_mute":
        m = not muted()
        powershell(_VOL_HELPER + f"[Audio]::SetMute(${'true' if m else 'false'})")
        return json_ok(muted=m)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def win_brightness(args: dict) -> str:
    action = args.get("action")
    level = args.get("level")
    base = (
        "$m = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue; "
        "$c = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness -ErrorAction SilentlyContinue; "
    )
    if action == "get":
        out = powershell(base + "$c.CurrentBrightness", check=False)
        if not out.strip().isdigit():
            return json_err("Яркость недоступна через WMI (внешний монитор без поддержки DDC/CI)")
        return json_ok(brightness=int(out.strip()))
    if action == "set":
        if level is None:
            return json_err("Для set нужен level 0–100")
        lv = max(0, min(100, int(level)))
        out = powershell(base + f"if ($m) {{ $m.WmiSetBrightness(1, {lv}); 'ok' }} else {{ 'no' }}", check=False)
        if out.strip() != "ok":
            return json_err("Яркость недоступна через WMI на этом мониторе (нужен внешний DDC/CI-инструмент, напр. ControlMyMonitor)")
        return json_ok(brightness=lv)
    if action in ("up", "down"):
        n = int(level or 10)
        out = powershell(base + "$c.CurrentBrightness", check=False)
        cur = int(out.strip()) if out.strip().isdigit() else 50
        lv = max(0, min(100, cur + (n if action == "up" else -n)))
        out = powershell(base + f"if ($m) {{ $m.WmiSetBrightness(1, {lv}); 'ok' }} else {{ 'no' }}", check=False)
        if out.strip() != "ok":
            return json_err("Яркость недоступна через WMI на этом мониторе")
        return json_ok(brightness=lv)
    return json_err(f"Неизвестное действие: {action}")


_THEME_KEY = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


@guarded
def win_dark_mode(args: dict) -> str:
    action = args.get("action")

    def is_dark() -> bool:
        out = powershell(f"(Get-ItemProperty -Path '{_THEME_KEY}' -Name AppsUseLightTheme -ErrorAction SilentlyContinue).AppsUseLightTheme", check=False)
        return out.strip() == "0"

    if action == "get":
        return json_ok(dark=is_dark())
    if action == "toggle":
        target = 0 if not is_dark() else 1
    elif action == "on":
        target = 0
    elif action == "off":
        target = 1
    else:
        return json_err(f"Неизвестное действие: {action}")
    powershell(
        f"New-ItemProperty -Path '{_THEME_KEY}' -Name AppsUseLightTheme -Value {target} -PropertyType DWord -Force | Out-Null; "
        f"New-ItemProperty -Path '{_THEME_KEY}' -Name SystemUsesLightTheme -Value {target} -PropertyType DWord -Force | Out-Null"
    )
    return json_ok(dark=target == 0)


@guarded
def win_power(args: dict) -> str:
    action = args.get("action")
    confirmed = bool(args.get("confirmed"))
    dangerous = {"restart", "shutdown", "logout", "hibernate"}
    if action in dangerous and not confirmed:
        return json_err(f"Действие «{action}» требует явного подтверждения пользователя. Переспросите и передайте confirmed=true.")
    if action == "lock":
        run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
        return json_ok(message="Экран заблокирован")
    if action == "sleep":
        powershell("Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)")
        return json_ok(message="Засыпаю")
    if action == "hibernate":
        run(["shutdown.exe", "/h"], check=False)
        return json_ok(message="Гибернация…")
    if action == "display_sleep":
        powershell(
            "Add-Type -Namespace W -Name U -MemberDefinition '[DllImport(\"user32.dll\")] public static extern int SendMessage(int hWnd, int hMsg, int wParam, int lParam);'; "
            "[W.U]::SendMessage(-1, 0x0112, 0xF170, 2) | Out-Null"
        )
        return json_ok(message="Экран выключен")
    if action == "screensaver":
        run(["cmd", "/c", "start", "", "scrnsave.scr", "/s"], check=False)
        return json_ok(message="Заставка запущена")
    if action == "restart":
        run(["shutdown.exe", "/r", "/t", "0"], check=False)
        return json_ok(message="Перезагрузка…")
    if action == "shutdown":
        run(["shutdown.exe", "/s", "/t", "0"], check=False)
        return json_ok(message="Выключение…")
    if action == "logout":
        run(["shutdown.exe", "/l"], check=False)
        return json_ok(message="Выход из системы…")
    return json_err(f"Неизвестное действие: {action}")


@guarded
def win_wifi(args: dict) -> str:
    action = args.get("action")
    if action in ("on", "off"):
        iface = powershell("(Get-NetAdapter | Where-Object {$_.InterfaceDescription -match 'Wi-Fi|Wireless|802.11'} | Select-Object -First 1).Name", check=False).strip()
        if not iface:
            return json_err("Wi-Fi адаптер не найден")
        run(["netsh", "interface", "set", "interface", iface, "admin=enable" if action == "on" else "admin=disable"], check=False)
        return json_ok(wifi=action, device=iface)
    if action == "status":
        out = run(["netsh", "wlan", "show", "interfaces"], check=False)
        ssid = ""
        power = "off"
        for line in out.splitlines():
            if line.strip().lower().startswith("ssid") and "bssid" not in line.lower():
                ssid = line.split(":", 1)[-1].strip()
            if line.strip().lower().startswith("state"):
                power = "on" if "connected" in line.lower() else "off"
        return json_ok(power=power, network=ssid)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def win_bluetooth(args: dict) -> str:
    action = args.get("action")
    if action == "status":
        out = powershell(
            "(Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Where-Object {$_.Status -eq 'OK'} | Measure-Object).Count",
            check=False,
        )
        return json_ok(power="on" if out.strip() not in ("", "0") else "unknown")
    if action in ("on", "off"):
        return json_err(
            "Windows не даёт программно включать/выключать радио Bluetooth без сторонних утилит "
            "(в отличие от blueutil на macOS). Откройте Параметры → Bluetooth и другие устройства, "
            "либо используйте BluetoothCommandLineTool.",
        )
    if action == "devices":
        out = powershell(
            "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Where-Object {$_.Status -eq 'OK'} | Select-Object -ExpandProperty FriendlyName",
            check=False,
        )
        return json_ok(connected=win.safe_list(out.splitlines()))
    return json_err(f"Неизвестное действие: {action}")


@guarded
def win_battery(args: dict) -> str:
    out = powershell(
        "$b = Get-WmiObject Win32_Battery -ErrorAction SilentlyContinue; "
        "if ($b) { "
        "$status = switch ($b.BatteryStatus) { 1 {'discharging'} 2 {'ac'} 6 {'charging'} default {'unknown'} }; "
        "\"$($b.EstimatedChargeRemaining)|$status\" "
        "} else { 'none' }",
        check=False,
    )
    out = out.strip()
    if out in ("", "none"):
        return json_err("На этом устройстве не обнаружено батареи (настольный ПК?)")
    pct_s, status = (out.split("|") + ["unknown"])[:2]
    try:
        pct = int(pct_s)
    except ValueError:
        pct = None
    return json_ok(percent=pct, charging=status == "charging", on_ac=status in ("ac", "charging"), raw=out)


@guarded
def win_system_info(args: dict) -> str:
    section = args.get("section") or "all"
    data: dict = {}
    if section in ("all", "hardware"):
        data["model"] = powershell("(Get-WmiObject Win32_ComputerSystem).Model", check=False)
        data["chip"] = powershell("(Get-WmiObject Win32_Processor).Name", check=False)
        data["windows"] = powershell("(Get-WmiObject Win32_OperatingSystem).Caption + ' ' + (Get-WmiObject Win32_OperatingSystem).Version", check=False)
        data["cores"] = powershell("(Get-WmiObject Win32_Processor).NumberOfCores", check=False)
    if section in ("all", "memory"):
        out = powershell(
            "$os = Get-WmiObject Win32_OperatingSystem; "
            "\"$([math]::Round($os.TotalVisibleMemorySize/1MB,1))|$([math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/$os.TotalVisibleMemorySize*100,1))\"",
            check=False,
        )
        total, used_pct = (out.strip().split("|") + ["?", "?"])[:2]
        data["memory_total_gb"] = total
        data["memory_used_percent"] = used_pct
    if section in ("all", "disk"):
        out = powershell(
            "Get-PSDrive -PSProvider FileSystem | ForEach-Object { \"$($_.Name): $([math]::Round($_.Free/1GB,1))GB free / $([math]::Round(($_.Used+$_.Free)/1GB,1))GB\" }",
            check=False,
        )
        data["disk"] = win.safe_list(out.splitlines())
    if section in ("all", "network"):
        data["local_ip"] = powershell(
            "(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
            "Where-Object {$_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1'} | Select-Object -First 1).IPAddress",
            check=False,
        )
        data["hostname"] = os.environ.get("COMPUTERNAME", "")
    if section in ("all", "uptime"):
        data["uptime"] = powershell(
            "$u = (Get-Date) - (Get-WmiObject Win32_OperatingSystem).ConvertToDateTime((Get-WmiObject Win32_OperatingSystem).LastBootUpTime); "
            "\"$($u.Days)d $($u.Hours)h $($u.Minutes)m\"",
            check=False,
        )
    if section in ("all", "processes"):
        out = powershell(
            "Get-Process | Sort-Object CPU -Descending | Select-Object -First 7 -Property ProcessName,CPU | "
            "ForEach-Object { \"$($_.ProcessName): $([math]::Round($_.CPU,1))\" }",
            check=False,
        )
        data["top_cpu"] = win.safe_list(out.splitlines())
    return json_ok(**data)


# ═══════════════════════════════ Медиа ═════════════════════════════════════

@guarded
def win_media(args: dict) -> str:
    action = args.get("action")
    player = win.detect_player(args.get("player") or _SETTINGS["default_player"])

    if player == "spotify":
        running = "spotify.exe" in run(["tasklist"], check=False).lower()
        if not running and action not in ("play_track", "play_playlist"):
            return json_err("Spotify не запущен")
        if action in ("play", "pause", "toggle"):
            # Spotify отвечает на медиа-клавиши, если активен/в фоне
            _media_key("playpause" if action != "play" or action == "toggle" else "playpause")
        elif action == "next":
            _media_key("next")
        elif action == "previous":
            _media_key("prev")
        elif action == "play_track":
            q = args.get("query", "")
            run(["cmd", "/c", "start", "", f"spotify:search:{q}"], check=False)
            return json_ok(player="Spotify", message=f"Открываю поиск Spotify: {q}")
        elif action == "play_playlist":
            q = args.get("query", "")
            run(["cmd", "/c", "start", "", f"spotify:search:{q}"], check=False)
            return json_ok(player="Spotify", message=f"Открываю поиск Spotify: {q}")
        elif action != "now_playing":
            return json_err(f"Неизвестное действие: {action}")
        title = powershell(
            "(Get-Process spotify -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowTitle} | Select-Object -First 1).MainWindowTitle",
            check=False,
        ).strip()
        if title and title.lower() != "spotify":
            artist, _, track = title.partition(" - ")
            return json_ok(player="Spotify", track=track or title, artist=artist if track else "")
        return json_ok(player="Spotify", state="unknown")

    # системный медиаплеер по умолчанию — управляем виртуальными медиа-клавишами
    if action in ("play", "pause", "toggle"):
        _media_key("playpause")
    elif action == "next":
        _media_key("next")
    elif action == "previous":
        _media_key("prev")
    elif action in ("play_track", "play_playlist"):
        return json_err("play_track/play_playlist поддерживается только для Spotify (player=spotify)")
    elif action != "now_playing":
        return json_err(f"Неизвестное действие: {action}")
    return json_ok(player="media", state="unknown", hint="Windows не даёт узнать 'что играет' без конкретного приложения (Spotify)")


def _media_key(kind: str) -> None:
    vk = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1}[kind]
    powershell(
        "Add-Type -Namespace W -Name K -MemberDefinition '"
        "[DllImport(\"user32.dll\")] public static extern void keybd_event(byte b, byte s, int f, int e);'; "
        f"[W.K]::keybd_event({vk}, 0, 0, 0); [W.K]::keybd_event({vk}, 0, 2, 0)",
        check=False,
    )


def _stop_speech() -> list[str]:
    """Остановить всё, что говорит вслух: SAPI-процесс и попросить HUD заглушить озвучку браузера."""
    killed = []
    try:
        r = subprocess.run(["taskkill", "/F", "/IM", "wscript.exe"], capture_output=True, timeout=3,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0:
            killed.append("say")
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
def win_say(args: dict) -> str:
    if args.get("action") == "stop":
        return json_ok(stopped=_stop_speech())
    text = args.get("text", "")
    if not text:
        return json_err("Пустой текст")
    _stop_speech()
    voice_line = f"$s.SelectVoice({as_ps(args['voice'])}); " if args.get("voice") else ""
    rate_line = f"$s.Rate = {int(args['rate'])}; " if args.get("rate") else ""
    script = (
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"{voice_line}{rate_line}$s.SpeakAsync({as_ps(text)}) | Out-Null"
    )
    subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return json_ok(spoken=text)


@guarded
def win_notify(args: dict) -> str:
    title, msg = args.get("title", "JARVIS"), args.get("message", "")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; "
        "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(0); "
        f"$xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode({as_ps(title)})) | Out-Null; "
        f"$xml.GetElementsByTagName('text')[1].AppendChild($xml.CreateTextNode({as_ps(msg)})) | Out-Null; "
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('JARVIS').Show($toast)"
    )
    try:
        powershell(script)
    except WinError:
        # запасной путь: msg или простое всплывающее окно через BurntToast недоступен — используем баллон трея через VBS-подобный toast
        powershell(
            "Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
            "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
            f"$n.ShowBalloonTip(4000, {as_ps(title)}, {as_ps(msg)}, [System.Windows.Forms.ToolTipIcon]::Info); "
            "Start-Sleep -Seconds 4; $n.Dispose()"
        )
    return json_ok(shown=True)


@guarded
def win_screenshot(args: dict) -> str:
    out_dir = Path(_SETTINGS["screenshot_dir"]).expanduser() if _SETTINGS.get("screenshot_dir") else win.cache_dir("screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / win.stamp("screen", "png")
    mode = args.get("mode") or "screen"
    if mode == "front_window":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "Add-Type -Namespace W -Name U -MemberDefinition '"
            "[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();"
            "[DllImport(\"user32.dll\")] public static extern bool GetWindowRect(IntPtr h, out RECT r);"
            "public struct RECT { public int L; public int T; public int R; public int B; }"
            "'; $h=[W.U]::GetForegroundWindow(); $r = New-Object W.U+RECT; [W.U]::GetWindowRect($h, [ref]$r) | Out-Null; "
            f"$w=$r.R-$r.L; $ht=$r.B-$r.T; $bmp = New-Object System.Drawing.Bitmap $w,$ht; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($r.L,$r.T,0,0,$bmp.Size); "
            f"$bmp.Save({as_ps(str(path))}, [System.Drawing.Imaging.ImageFormat]::Png)"
        )
    else:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
            "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
            "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
            "$g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size); "
            f"$bmp.Save({as_ps(str(path))}, [System.Drawing.Imaging.ImageFormat]::Png)"
        )
    powershell(script, timeout=15)
    if not path.exists():
        return json_err("Скриншот не создан")
    return json_ok(path=str(path), hint="Передайте path в vision_analyze, чтобы описать содержимое экрана")


@guarded
def win_camera_snap(args: dict) -> str:
    bin_ = which("ffmpeg")
    if not bin_:
        return json_err("Нужен ffmpeg (winget install ffmpeg) для снимка с камеры")
    out_dir = win.cache_dir("camera")
    path = out_dir / win.stamp("cam", "jpg")
    device = powershell(
        "$d = (ffmpeg -list_devices true -f dshow -i dummy 2>&1 | Select-String '\"(.*?)\" \\(video\\)'); "
        "if ($d) { ($d[0] -replace '.*\"(.*?)\".*', '$1') }",
        check=False,
    ).strip() or "default"
    warmup = float(args.get("warmup") or 1.0)
    run([bin_, "-y", "-f", "dshow", "-i", f"video={device}", "-frames:v", "1", str(path)], timeout=int(10 + warmup), check=False)
    if not path.exists():
        return json_err("Не удалось получить снимок с камеры")
    return json_ok(path=str(path), hint="Передайте path в vision_analyze")


@guarded
def win_wallpaper(args: dict) -> str:
    p = Path(args.get("path", "")).expanduser()
    if not p.exists():
        return json_err(f"Файл не найден: {p}")
    powershell(
        "Add-Type -Namespace W -Name P -MemberDefinition '"
        "[DllImport(\"user32.dll\", CharSet=CharSet.Auto)] public static extern int SystemParametersInfo(int u, int p, string v, int f);'; "
        f"[W.P]::SystemParametersInfo(20, 0, {as_ps(str(p))}, 3) | Out-Null"
    )
    return json_ok(wallpaper=str(p))


# ═══════════════════════════════ Продуктивность ════════════════════════════

def _outlook_available() -> bool:
    out = powershell("try { New-Object -ComObject Outlook.Application | Out-Null; 'ok' } catch { 'no' }", check=False)
    return out.strip() == "ok"


def _events_for_day(day: dt.date) -> list[dict]:
    """Список событий Outlook-календаря на дату через COM."""
    script = f'''
    try {{
        $ol = New-Object -ComObject Outlook.Application
        $ns = $ol.GetNamespace("MAPI")
        $cal = $ns.GetDefaultFolder(9)
        $items = $cal.Items
        $items.IncludeRecurrences = $true
        $items.Sort("[Start]")
        $start = Get-Date -Year {day.year} -Month {day.month} -Day {day.day} -Hour 0 -Minute 0 -Second 0
        $end = $start.AddDays(1)
        $filter = "[Start] >= '" + $start.ToString("g") + "' AND [Start] < '" + $end.ToString("g") + "'"
        $evs = $items.Restrict($filter)
        foreach ($e in $evs) {{
            Write-Output ($e.Subject + "|" + $e.Start.ToString("HH:mm") + "|" + $e.End.ToString("HH:mm"))
        }}
    }} catch {{ Write-Output "ERR:$($_.Exception.Message)" }}
    '''
    out = powershell(script, timeout=30, check=False)
    if out.strip().startswith("ERR:"):
        raise WinError(f"Outlook недоступен или не настроен: {out.strip()[4:]}")
    events = []
    for line in win.safe_list(out.splitlines()):
        parts = line.split("|")
        if len(parts) >= 3:
            events.append({"calendar": "Outlook", "title": parts[0], "start": parts[1], "end": parts[2]})
    events.sort(key=lambda e: e["start"])
    return events


@guarded
def win_calendar(args: dict) -> str:
    action = args.get("action")
    today = dt.date.today()
    if not _outlook_available() and action != "create":
        return json_err(
            "Outlook не установлен/не настроен. Настройте профиль Outlook или используйте win_reminders "
            "для локальных напоминаний.",
        )
    if action == "today":
        return json_ok(date=str(today), events=_events_for_day(today))
    if action == "tomorrow":
        d = today + dt.timedelta(days=1)
        return json_ok(date=str(d), events=_events_for_day(d))
    if action == "on_date":
        d = dt.date.fromisoformat(args["date"])
        return json_ok(date=str(d), events=_events_for_day(d))
    if action == "create":
        title = args.get("title") or "Событие"
        d = dt.date.fromisoformat(args.get("date") or str(today))
        hh, mm = (args.get("start_time") or "12:00").split(":")
        dur = int(args.get("duration_min") or 60)
        script = f'''
        try {{
            $ol = New-Object -ComObject Outlook.Application
            $appt = $ol.CreateItem(1)
            $appt.Subject = {as_ps(title)}
            $appt.Start = Get-Date -Year {d.year} -Month {d.month} -Day {d.day} -Hour {int(hh)} -Minute {int(mm)} -Second 0
            $appt.Duration = {dur}
            $appt.Save()
            Write-Output "ok"
        }} catch {{ Write-Output "ERR:$($_.Exception.Message)" }}
        '''
        out = powershell(script, timeout=30, check=False)
        if out.strip().startswith("ERR:"):
            return json_err(f"Не удалось создать событие: {out.strip()[4:]}")
        return json_ok(created=title, date=str(d), start=f"{int(hh):02d}:{int(mm):02d}", duration_min=dur)
    return json_err(f"Неизвестное действие: {action}")


def _reminders_file() -> Path:
    p = win.hermes_home() / "jarvis" / "reminders.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("[]", encoding="utf-8")
    return p


@guarded
def win_reminders(args: dict) -> str:
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
    p = win.hermes_home() / "jarvis" / "notes"
    p.mkdir(parents=True, exist_ok=True)
    return p


@guarded
def win_notes(args: dict) -> str:
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
def win_clipboard(args: dict) -> str:
    if args.get("action") == "get":
        out = powershell("Get-Clipboard -Raw", check=False)
        return json_ok(text=out)
    if args.get("action") == "set":
        text = args.get("text") or ""
        subprocess.run(["clip.exe"], input=text.encode("utf-16-le"), check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return json_ok(copied=True)
    return json_err("action должен быть get или set")


_SPECIAL_KEYS = {
    "return": "{ENTER}", "enter": "{ENTER}", "tab": "{TAB}", "space": " ", "escape": "{ESC}", "esc": "{ESC}",
    "delete": "{DEL}", "backspace": "{BACKSPACE}", "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
}
_MOD_PREFIX = {"ctrl": "^", "control": "^", "alt": "%", "shift": "+", "win": ""}  # win-модификатор SendKeys не поддерживает


@guarded
def win_type(args: dict) -> str:
    action = args.get("action")
    text = args.get("text", "")
    if action == "type_text":
        escaped = text.replace("{", "{{}").replace("}", "{}}").replace("+", "{+}").replace("^", "{^}").replace("%", "{%}").replace("~", "{~}")
        powershell(
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait({as_ps(escaped)})"
        )
        return json_ok(typed=len(text))
    if action == "keystroke":
        mods = []
        for m in args.get("modifiers") or []:
            key = str(m).lower()
            if key not in _MOD_PREFIX:
                return json_err(f"Неизвестный модификатор {m!r}; допустимы: ctrl, alt, shift, win")
            mods.append(key)
        key = text.lower()
        keycode = _SPECIAL_KEYS.get(key, text)
        prefix = "".join(_MOD_PREFIX[m] for m in mods)
        combo = f"{prefix}({keycode})" if len(keycode) > 1 or prefix else f"{prefix}{keycode}"
        powershell(
            "Add-Type -AssemblyName System.Windows.Forms; "
            f"[System.Windows.Forms.SendKeys]::SendWait({as_ps(combo)})"
        )
        return json_ok(pressed=text, modifiers=mods)
    return json_err(f"Неизвестное действие: {action}")


@guarded
def win_window(args: dict) -> str:
    action = args.get("action")
    app = args.get("app")
    helper = (
        "Add-Type -Namespace W -Name U -MemberDefinition '"
        "[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();"
        "[DllImport(\"user32.dll\")] public static extern bool ShowWindowAsync(IntPtr h, int n);"
        "[DllImport(\"user32.dll\")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);"
        "[DllImport(\"user32.dll\")] public static extern int GetWindowThreadProcessId(IntPtr h, out int pid);"
        "'; "
    )
    if app:
        target = f"(Get-Process -Name {as_ps(app)} -ErrorAction SilentlyContinue | Select-Object -First 1).MainWindowHandle"
    else:
        target = "[W.U]::GetForegroundWindow()"
    if action == "list":
        out = powershell("Get-Process | Where-Object { $_.MainWindowTitle } | Select-Object -ExpandProperty MainWindowTitle", check=False)
        return json_ok(app=app or "*", windows=win.safe_list(out.splitlines()))
    screen = (
        "Add-Type -AssemblyName System.Windows.Forms; $wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea; "
    )
    if action == "minimize":
        powershell(helper + f"[W.U]::ShowWindowAsync({target}, 6) | Out-Null")
    elif action == "maximize":
        powershell(helper + f"[W.U]::ShowWindowAsync({target}, 3) | Out-Null")
    elif action == "left_half":
        powershell(helper + screen + f"[W.U]::MoveWindow({target}, $wa.X, $wa.Y, [int]($wa.Width/2), $wa.Height, $true) | Out-Null")
    elif action == "right_half":
        powershell(helper + screen + f"[W.U]::MoveWindow({target}, $wa.X + [int]($wa.Width/2), $wa.Y, [int]($wa.Width/2), $wa.Height, $true) | Out-Null")
    elif action == "center":
        powershell(helper + screen + f"$cw=[int]($wa.Width*0.7); $ch=[int]($wa.Height*0.7); "
                                       f"[W.U]::MoveWindow({target}, $wa.X + [int](($wa.Width-$cw)/2), $wa.Y + [int](($wa.Height-$ch)/2), $cw, $ch, $true) | Out-Null")
    else:
        return json_err(f"Неизвестное действие: {action}")
    return json_ok(app=app or "(активное)", action=action)


def _shortcuts_dir() -> Path:
    p = win.hermes_home() / "jarvis" / "shortcuts"
    p.mkdir(parents=True, exist_ok=True)
    return p


@guarded
def win_shortcut(args: dict) -> str:
    action = args.get("action") or "run"
    d = _shortcuts_dir()
    if action == "list":
        names = sorted({f.stem for f in d.glob("*.ps1")} | {f.stem for f in d.glob("*.bat")})
        return json_ok(shortcuts=names)
    name = args.get("name")
    if not name:
        return json_err("Нужно имя команды (name)")
    script = d / f"{name}.ps1"
    bat = d / f"{name}.bat"
    inp = args.get("input") or ""
    if script.exists():
        proc = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), inp],
                              capture_output=True, timeout=120, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    elif bat.exists():
        proc = subprocess.run([str(bat), inp], capture_output=True, timeout=120, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        return json_err(f"Скрипт не найден: {d}\\{name}.ps1|.bat")
    if proc.returncode != 0:
        return json_err((proc.stderr or "").strip() or f"Код {proc.returncode}")
    return json_ok(ran=name, output=(proc.stdout or "").strip())


@guarded
def win_contacts(args: dict) -> str:
    """Контакты Outlook (COM): поиск и выгрузка для импорта в базу знаний."""
    action = args.get("action") or "search"
    limit = int(args.get("limit") or 20)
    if not _outlook_available():
        return json_err("Outlook не установлен/не настроен")
    if action == "search":
        q = (args.get("query") or "").strip()
        if not q:
            return json_err("Нужен query")
        script = f'''
        try {{
            $ol = New-Object -ComObject Outlook.Application
            $ns = $ol.GetNamespace("MAPI")
            $contacts = $ns.GetDefaultFolder(10).Items
            $found = $contacts.Restrict("[FullName] Like '%{args.get("query", "").strip()}%'")
            $n = 0
            foreach ($c in $found) {{
                if ($n -ge {limit}) {{ break }}
                Write-Output ($c.FullName + "|" + $c.Email1Address + "|" + $c.BusinessTelephoneNumber + "|" + $c.CompanyName)
                $n++
            }}
        }} catch {{ Write-Output "ERR:$($_.Exception.Message)" }}
        '''
    elif action == "list":
        script = f'''
        try {{
            $ol = New-Object -ComObject Outlook.Application
            $ns = $ol.GetNamespace("MAPI")
            $contacts = $ns.GetDefaultFolder(10).Items
            $n = 0
            foreach ($c in $contacts) {{
                if ($n -ge {limit}) {{ break }}
                if ($c.CompanyName) {{ Write-Output ($c.FullName + "|||" + $c.CompanyName); $n++ }}
            }}
        }} catch {{ Write-Output "ERR:$($_.Exception.Message)" }}
        '''
    else:
        return json_err(f"Неизвестное действие: {action}")
    out = powershell(script, timeout=60, check=False)
    if out.strip().startswith("ERR:"):
        return json_err(out.strip()[4:])
    rows, seen = [], set()
    for line in win.safe_list(out.splitlines()):
        parts = (line.split("|") + ["", "", "", ""])[:4]
        name = parts[0].strip()
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append({"name": name, "email": parts[1].strip(), "phone": parts[2].strip(), "org": parts[3].strip()})
    return json_ok(action=action, count=len(rows), contacts=rows)


@guarded
def win_focus(args: dict) -> str:
    """Focus Assist Windows (реестр CurrentUserSession\\QuietHours)."""
    action = args.get("action") or "get"
    key = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\Cache\DefaultAccount\Current\windows.data.notifications.quiethoursprofile\Current"
    if action == "get":
        powershell(
            "$p = Get-ItemProperty -Path '" + key + "' -Name Data -ErrorAction SilentlyContinue; "
            "if ($p) { 'present' } else { 'unknown' }",
            check=False,
        )
        # Windows не документирует стабильный публичный API для точного статуса Focus Assist в PowerShell;
        # честно сообщаем об ограничении вместо того чтобы гадать.
        return json_ok(focus="", active=False, note="Windows не предоставляет надёжный публичный способ прочитать статус Focus Assist из скрипта; используйте Центр уведомлений.")
    if action == "set":
        name = (args.get("name") or "").strip().lower()
        if name not in ("on", "off", "priority"):
            return json_err("Нужно name: on | off | priority")
        # Включение через WNF/CCS недокументировано и требует стороннего инструмента; предлагаем ярлык.
        return json_err(
            "Windows не даёt программно переключать Focus Assist через штатный PowerShell. "
            "Создайте на рабочем столе ярлык на 'ms-settings:quiethours' или используйте автоматизацию "
            "с помощью стороннего инструмента (например, FocusAssist CLI).",
        )
    return json_err(f"Неизвестное действие: {action}")


@guarded
def win_file_manage(args: dict) -> str:
    """Файловые операции «по-виндовому»: удаление только в Корзину."""
    action = args.get("action")
    src = Path(win.resolve_target(args.get("path", ""))) if args.get("path") else None
    if action == "trash":
        if not src or not src.exists():
            return json_err("Файл не найден")
        try:
            import send2trash  # type: ignore
            send2trash.send2trash(str(src))
        except ImportError:
            method = "DeleteDirectory" if src.is_dir() else "DeleteFile"
            powershell(
                "Add-Type -AssemblyName Microsoft.VisualBasic; "
                f"[Microsoft.VisualBasic.FileIO.FileSystem]::{method}"
                f"({as_ps(str(src))}, 'OnlyErrorDialogs', 'SendToRecycleBin')"
            )
        return json_ok(trashed=str(src))
    if action == "rename":
        new_name = args.get("new_name", "").strip()
        if not src or not src.exists() or not new_name or "\\" in new_name or "/" in new_name:
            return json_err("Нужны существующий path и new_name без «/» «\\»")
        dst = src.with_name(new_name)
        if dst.exists():
            return json_err(f"Уже существует: {dst}")
        src.rename(dst)
        return json_ok(renamed=str(dst))
    if action == "move":
        dst_dir = Path(win.resolve_target(args.get("destination", "")))
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
def win_powershell(args: dict) -> str:
    if not _SETTINGS.get("allow_raw_powershell"):
        return json_err(
            "Выполнение произвольного PowerShell отключено. Включите в config.yaml Hermes: "
            "plugins.entries.jarvis-windows.settings.allow_raw_powershell: true"
        )
    out = powershell(args.get("script", ""), timeout=120)
    return json_ok(output=out)


# ─────────────────────────── таблица «имя → обработчик» ────────────────────

HANDLERS = {
    "win_app": win_app,
    "win_open": win_open,
    "win_search": win_search,
    "win_explorer": win_explorer,
    "win_volume": win_volume,
    "win_brightness": win_brightness,
    "win_dark_mode": win_dark_mode,
    "win_power": win_power,
    "win_wifi": win_wifi,
    "win_bluetooth": win_bluetooth,
    "win_battery": win_battery,
    "win_system_info": win_system_info,
    "win_media": win_media,
    "win_say": win_say,
    "win_notify": win_notify,
    "win_screenshot": win_screenshot,
    "win_camera_snap": win_camera_snap,
    "win_wallpaper": win_wallpaper,
    "win_calendar": win_calendar,
    "win_reminders": win_reminders,
    "win_notes": win_notes,
    "win_clipboard": win_clipboard,
    "win_type": win_type,
    "win_window": win_window,
    "win_shortcut": win_shortcut,
    "win_file_manage": win_file_manage,
    "win_contacts": win_contacts,
    "win_focus": win_focus,
    "win_powershell": win_powershell,
}
