#!/usr/bin/env python3
"""
JARVIS selftest — проверка платформенного слоя (macOS: jarvis-macos, Windows: jarvis-windows,
Linux: jarvis-linux) на РЕАЛЬНОЙ машине без LLM.

Прогоняет каждый mac_*/win_*/linux_* инструмент в безопасном (read-only) режиме и печатает таблицу:
    ✔ работает  ·  ⚠ нет прав/нужна настройка → что сделать  ·  ✖ сломано (текст ошибки)
Ничего не меняет в системе: не трогает громкость, окна, файлы; не отправляет сообщений.

Запуск:  jarvis selftest        (или python3 <jarvis_home>/selftest.py [--json] [--fix])
  --fix   macOS: открыть панели Системных настроек для всех «⚠ нет прав»
          Windows/Linux: ничего опасного не чинит автоматически, только рекомендации
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

# На Windows stdout/stderr при перенаправлении в файл/пайп (не TTY) используют системную
# кодировку консоли (обычно cp1252), а не UTF-8 — любой print() с кириллицей тогда падает
# с UnicodeEncodeError вместо того, чтобы просто напечататься. На Linux/macOS это не нужно
# (там локаль почти всегда UTF-8), поэтому ограничиваемся Windows.
if sys.platform == "win32":  # pragma: no cover — покрыто CI на windows-latest
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
if IS_WINDOWS:
    PLUGIN_NAME = "jarvis-windows"
elif IS_LINUX:
    PLUGIN_NAME = "jarvis-linux"
else:
    PLUGIN_NAME = "jarvis-macos"

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (os.environ.get("LOCALAPPDATA", "") + "/hermes" if IS_WINDOWS else "~/.hermes")).expanduser()
# Порядок: рядом со скриптом (репозиторий или $HERMES_HOME/jarvis) → установленный плагин.
# Так selftest из свежего архива проверяет свежий код, а не старую установленную копию.
_HERE = Path(__file__).resolve().parent
CANDIDATES = [
    _HERE.parent / "plugins" / PLUGIN_NAME,   # запуск из репозитория: scripts/selftest.py
    _HERE / "plugins" / PLUGIN_NAME,          # запуск из $HERMES_HOME/jarvis/selftest.py (копия плагинов рядом)
    HERMES_HOME / "plugins" / PLUGIN_NAME,    # установленный плагин
]

# подстрока (без учёта регистра) в тексте ошибки → (панель, URL); macOS локализует ошибки
PERMISSION_HINTS_MAC = {
    "accessibility": ("Универсальный доступ", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    "assistive access": ("Универсальный доступ", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    "упрощенного доступа": ("Универсальный доступ", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    "упрощённого доступа": ("Универсальный доступ", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
    "автоматизац": ("Автоматизация", "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"),
    "not authorized": ("Автоматизация", "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"),
    "не разрешено отправлять": ("Автоматизация", "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"),
    "-1743": ("Автоматизация", "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"),
    "screen": ("Запись экрана", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"),
    "запись экрана": ("Запись экрана", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"),
    "full disk": ("Полный доступ к диску", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"),
    "полный доступ к диску": ("Полный доступ к диску", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"),
    "камер": ("Камера", "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"),
}

# подстрока (без учёта регистра) в тексте ошибки → человекочитаемая подсказка; Windows не даёт единой панели
# приватности, часть прав — это отсутствующие утилиты/фичи, часть — настройка сторонних приложений
PERMISSION_HINTS_WIN = {
    "access is denied": "Запустите терминал/JARVIS от имени администратора либо проверьте политики групповой безопасности",
    "отказано в доступе": "Запустите терминал/JARVIS от имени администратора либо проверьте политики групповой безопасности",
    "not recognized": "Утилита не найдена в PATH — установите нужный компонент (см. описание инструмента)",
    "не является внутренней или внешней": "Утилита не найдена в PATH — установите нужный компонент (см. описание инструмента)",
    "outlook": "Outlook не установлен или не настроен — календарь/контакты будут недоступны, это не ошибка JARVIS",
    "com object": "COM-компонент недоступен (Outlook/Windows Search) — переустановите/настройте соответствующее приложение",
    "ddc": "Монитор не поддерживает DDC/CI — регулировка яркости через WMI недоступна на этом экране",
    "blueutil": "Bluetooth-модуль недоступен или выключен в диспетчере устройств",
    "camera": "Камера занята другим приложением или недоступна",
    "камер": "Камера занята другим приложением или недоступна",
}

# подстрока (без учёта регистра) в тексте ошибки → человекочитаемая подсказка для Linux;
# на Linux «прав» в смысле macOS/Windows почти нет — большинство ⚠ это отсутствующие консольные утилиты
PERMISSION_HINTS_LINUX = {
    "нужен xdotool": "sudo apt install xdotool  (X11: набор текста, окна, активное приложение)",
    "нужен wmctrl": "sudo apt install wmctrl  (список/управление окнами)",
    "нужен pactl": "PipeWire/PulseAudio обычно уже установлены; либо используйте amixer (alsa-utils)",
    "нужен brightnessctl": "sudo apt install brightnessctl  (яркость экрана)",
    "нужен nmcli": "NetworkManager не установлен/не запущен — sudo apt install network-manager",
    "нужен bluetoothctl": "sudo apt install bluez",
    "нужен upower": "sudo apt install upower",
    "нужен notify-send": "sudo apt install libnotify-bin",
    "нужен espeak": "sudo apt install espeak-ng",
    "нужен xclip": "sudo apt install xclip  (X11) или wl-clipboard (Wayland)",
    "нужен grim": "sudo apt install grim slurp  (Wayland: скриншоты)",
    "нужен scrot": "sudo apt install scrot  (X11: скриншоты)",
    "нужен gio": "glib2 обычно уже установлен; либо trash-cli для Корзины",
    "нужен playerctl": "sudo apt install playerctl  (управление медиа через MPRIS)",
    "нужен khal": "pip install khal  (CLI-календарь; опционально)",
    "не найдена в path": "Утилита не установлена — см. подсказку выше",
    "gnome": "Доступно только на GNOME (gsettings) — на других окружениях переключите вручную",
}

# (инструмент, аргументы, что проверяем) — только чтение
CHECKS_MAC = [
    ("mac_app", {"action": "list_running"}, "System Events: список приложений"),
    ("mac_volume", {"action": "get"}, "громкость"),
    ("mac_dark_mode", {"action": "get"}, "тема оформления"),
    ("mac_battery", {}, "pmset"),
    ("mac_system_info", {"section": "hardware"}, "sysctl/sw_vers"),
    ("mac_system_info", {"section": "network"}, "сеть"),
    ("mac_wifi", {"action": "status"}, "networksetup"),
    ("mac_bluetooth", {"action": "status"}, "blueutil (brew)"),
    ("mac_media", {"action": "now_playing"}, "Music/Spotify"),
    ("mac_clipboard", {"action": "get"}, "pbpaste"),
    ("mac_spotlight", {"query": "kMDItemKind == 'Application'", "limit": 1}, "mdfind"),
    ("mac_window", {"action": "list"}, "окна (Accessibility)"),
    ("mac_calendar", {"action": "today"}, "Calendar.app (Автоматизация)"),
    ("mac_reminders", {"action": "list"}, "Reminders.app (Автоматизация)"),
    ("mac_notes", {"action": "search", "query": "jarvis-selftest-nonexistent"}, "Notes.app (Автоматизация)"),
    ("mac_contacts", {"action": "search", "query": "zzz-nonexistent"}, "Contacts.app (Автоматизация)"),
    ("mac_shortcut", {"action": "list"}, "Shortcuts"),
    ("mac_screenshot", {"target": "screen"}, "screencapture (Запись экрана)"),
    ("mac_focus", {"action": "get"}, "Focus (DoNotDisturb DB)"),
    ("mac_file_manage", {"action": "list", "path": "~/Downloads", "limit": 3}, "файлы"),
    ("mac_notify", {"title": "JARVIS selftest", "message": "Уведомления работают"}, "display notification"),
]

CHECKS_WIN = [
    ("win_app", {"action": "list_running"}, "список процессов (Get-Process)"),
    ("win_volume", {"action": "get"}, "громкость (Core Audio)"),
    ("win_dark_mode", {"action": "get"}, "тема оформления (реестр)"),
    ("win_battery", {}, "батарея (WMI Win32_Battery)"),
    ("win_system_info", {"section": "hardware"}, "оборудование (WMI/CIM)"),
    ("win_system_info", {"section": "network"}, "сеть"),
    ("win_wifi", {"action": "status"}, "netsh wlan"),
    ("win_bluetooth", {"action": "status"}, "Bluetooth-радио"),
    ("win_media", {"action": "now_playing"}, "текущий трек (SMTC/Spotify)"),
    ("win_clipboard", {"action": "get"}, "буфер обмена"),
    ("win_search", {"query": "*.txt", "limit": 1}, "поиск файлов"),
    ("win_window", {"action": "list"}, "список окон"),
    ("win_calendar", {"action": "today"}, "Outlook Calendar (COM)"),
    ("win_reminders", {"action": "list"}, "локальные напоминания"),
    ("win_notes", {"action": "search", "query": "jarvis-selftest-nonexistent"}, "заметки (.md)"),
    ("win_contacts", {"action": "search", "query": "zzz-nonexistent"}, "Outlook Contacts (COM)"),
    ("win_shortcut", {"action": "list"}, "скрипты shortcuts/"),
    ("win_screenshot", {"mode": "screen"}, "скриншот экрана"),
    ("win_focus", {"action": "get"}, "Focus Assist (нет публичного API — вернёт success с пометкой)"),
    ("win_file_manage", {"action": "list", "path": "~/Downloads", "limit": 3}, "файлы"),
    ("win_notify", {"title": "JARVIS selftest", "message": "Уведомления работают"}, "toast/balloon notification"),
]

CHECKS_LINUX = [
    ("linux_app", {"action": "list_running"}, "список приложений (wmctrl/ps)"),
    ("linux_volume", {"action": "get"}, "громкость (pactl/amixer)"),
    ("linux_dark_mode", {"action": "get"}, "тема оформления (gsettings, GNOME)"),
    ("linux_battery", {}, "батарея (upower/sysfs)"),
    ("linux_system_info", {"section": "hardware"}, "оборудование (os-release/lscpu)"),
    ("linux_system_info", {"section": "network"}, "сеть"),
    ("linux_wifi", {"action": "status"}, "nmcli (NetworkManager)"),
    ("linux_bluetooth", {"action": "status"}, "bluetoothctl (BlueZ)"),
    ("linux_media", {"action": "now_playing"}, "MPRIS (playerctl)"),
    ("linux_clipboard", {"action": "get"}, "буфер обмена (xclip/wl-clipboard)"),
    ("linux_search", {"query": "*.txt", "limit": 1}, "поиск файлов (locate/find)"),
    ("linux_window", {"action": "list"}, "список окон (wmctrl)"),
    ("linux_calendar", {"action": "today"}, "khal (CalDAV, опционально)"),
    ("linux_reminders", {"action": "list"}, "локальные напоминания"),
    ("linux_notes", {"action": "search", "query": "jarvis-selftest-nonexistent"}, "заметки (.md)"),
    ("linux_shortcut", {"action": "list"}, "скрипты shortcuts/"),
    ("linux_screenshot", {"mode": "screen"}, "скриншот экрана (grim/scrot/…)"),
    ("linux_focus", {"action": "get"}, "«Не беспокоить» (gsettings, GNOME)"),
    ("linux_file_manage", {"action": "list", "path": "~/Downloads", "limit": 3}, "файлы"),
    ("linux_notify", {"title": "JARVIS selftest", "message": "Уведомления работают"}, "notify-send"),
]

if IS_WINDOWS:
    CHECKS = CHECKS_WIN
elif IS_LINUX:
    CHECKS = CHECKS_LINUX
else:
    CHECKS = CHECKS_MAC


def load_plugin(explicit: str | None = None):
    bases = [Path(explicit).expanduser()] if explicit else CANDIDATES
    for base in bases:
        if (base / "__init__.py").exists():
            spec = importlib.util.spec_from_file_location("jarvis_platform_selftest", base / "__init__.py",
                                                          submodule_search_locations=[str(base)])
            mod = importlib.util.module_from_spec(spec)
            sys.modules["jarvis_platform_selftest"] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod, base
    raise SystemExit(f"Плагин {PLUGIN_NAME} не найден ни в {HERMES_HOME}/plugins, ни в репозитории")


def classify(result: dict):
    """→ (статус, комментарий[, url панели настроек — только macOS])"""
    if result.get("success"):
        return ("ok", "", None) if not (IS_WINDOWS or IS_LINUX) else ("ok", "")
    err = (result.get("error", "") + " " + result.get("hint", "")).lower()
    if IS_WINDOWS:
        if "unsupported" in err or "не поддерживается" in err or "нет публичного api" in err:
            return "unsupported", err.strip()[:110]
        for key, hint in PERMISSION_HINTS_WIN.items():
            if key in err:
                return "perm", hint
        return "fail", err.strip()[:110]
    if IS_LINUX:
        if "нужен" in err or "не найден" in err or "не найдена" in err:
            for key, hint in PERMISSION_HINTS_LINUX.items():
                if key in err:
                    return "missing", hint
            return "missing", err.strip()[:110]
        if "поддерживается только на gnome" in err or "не поддерживается" in err:
            return "unsupported", err.strip()[:110]
        return "fail", err.strip()[:110]
    for key, (label, url) in PERMISSION_HINTS_MAC.items():
        if key in err:
            return "perm", f"нет прав: {label}", url
    if "не найден" in err and ("brew" in err or "команда не найдена" in err):
        return "missing", err.strip()[:90], None
    return "fail", err.strip()[:110], None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix", action="store_true", help="macOS: открыть панели настроек для недостающих прав")
    ap.add_argument("--plugin", help=f"путь к папке плагина {PLUGIN_NAME} (по умолчанию: репозиторий → $HERMES_HOME/plugins)")
    args = ap.parse_args()

    if IS_WINDOWS:
        expected_system = "Windows"
    elif IS_LINUX:
        expected_system = "Linux"
    else:
        expected_system = "Darwin"
    if platform.system() != expected_system:
        print(f"selftest (эта сборка) имеет смысл только на {expected_system}", file=sys.stderr)
    mod, base = load_plugin(args.plugin)
    handlers = mod.tools.HANDLERS
    missing = [name for name, _, _ in CHECKS if name not in handlers]
    if IS_WINDOWS:
        reinstall_hint = "install.ps1 -Yes -NoScheduledTask"
    elif IS_LINUX:
        reinstall_hint = "bash install.linux.sh --yes --no-systemd-user --no-system-packages"
    else:
        reinstall_hint = "bash install.sh --yes --no-launchd --no-brew-tools"
    if missing and not args.json:
        print(f"  ! плагин по пути {base} старее этого selftest (нет {', '.join(sorted(set(missing)))}) — "
              f"переустановите: {reinstall_hint}")
    rows, panels = [], []
    for name, a, what in CHECKS:
        fn = handlers.get(name)
        if not fn:
            rows.append({"tool": name, "status": "outdated", "note": "нет в установленном плагине (старая версия)", "what": what, "ms": 0})
            continue
        t0 = time.time()
        try:
            res = json.loads(fn(a))
        except Exception as e:
            res = {"success": False, "error": f"{type(e).__name__}: {e}"}
        ms = int((time.time() - t0) * 1000)
        classified = classify(res)
        if IS_WINDOWS or IS_LINUX:
            st, note = classified
            url = None
        else:
            st, note, url = classified
        if url:
            panels.append(url)
        rows.append({"tool": name, "status": st, "note": note, "what": what, "ms": ms})

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        icon = {"ok": "✔", "perm": "⚠", "missing": "◌", "unsupported": "◌", "fail": "✖", "outdated": "↻"}
        print(f"\nJARVIS selftest · {platform.platform()} · плагин: {base}\n")
        for r in rows:
            print(f"  {icon[r['status']]}  {r['tool']:<18} {r['what']:<38} {r['ms']:>5} мс  {r['note']}")
        ok = sum(r["status"] == "ok" for r in rows)
        perm = sum(r["status"] == "perm" for r in rows)
        fail = sum(r["status"] == "fail" for r in rows)
        miss = sum(r["status"] in ("missing", "unsupported") for r in rows)
        old = sum(r["status"] == "outdated" for r in rows)
        if IS_WINDOWS:
            miss_label = "не поддерживается на Windows"
        elif IS_LINUX:
            miss_label = "нет утилиты/не поддерживается на этом окружении"
        else:
            miss_label = "нет утилиты (brew)"
        print(f"\n  итого: {ok} работает · {perm} нет прав/нужна настройка · {miss} {miss_label} · {fail} сломано"
              + (f" · {old} требуют переустановки плагина" if old else "") + "\n")
        if perm:
            if IS_WINDOWS:
                print("  Часть прав в Windows выдаётся через UAC/групповые политики, часть — через настройку сторонних\n"
                      "  приложений (Outlook и т.п.). Смотрите подсказку в колонке справа для каждого пункта.\n")
            elif IS_LINUX:
                print("  На Linux «прав» в смысле macOS почти нет — большинство ⚠/◌ означают отсутствующую консольную\n"
                      "  утилиту (см. подсказку в колонке справа) — доустановите её пакетным менеджером.\n")
            else:
                print("  Права выдаются терминалу, из которого запущен JARVIS (Terminal / iTerm / Warp).\n")
                print("  Запустите с --fix, чтобы открыть нужные панели, затем перезапустите терминал и повторите.\n")
        if fail:
            print("  «✖ сломано» — пришлите вывод `jarvis selftest --json` разработчику или JARVIS'у: «почини selftest».\n")
    if args.fix and IS_MAC:
        for url in dict.fromkeys(panels):
            subprocess.run(["open", url], check=False)
    return 0 if not any(r["status"] == "fail" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
