"""
jarvis-linux — плагин Hermes Agent, дающий агенту «руки» на Linux (X11/Wayland).

Зеркало jarvis-macos/jarvis-windows: та же архитектура register(ctx), тот же набор
функций (app control, volume, brightness, screenshots, calendar, reminders, notes…),
но реализовано через стандартные утилиты рабочего стола Linux (wmctrl/xdotool,
pactl/amixer, nmcli, bluetoothctl, upower, grim/scrot, xclip/wl-clipboard,
notify-send, espeak-ng…) вместо AppleScript/PowerShell.

Точка входа — register(ctx). Hermes вызывает её один раз при старте:
  1. читаем настройки плагина (plugins.entries.jarvis-linux.settings);
  2. регистрируем каждый инструмент: схема (для модели) + обработчик (код);
  3. регистрируем slash-команды для быстрого доступа из чата.

Все инструменты объединены в toolset «jarvis_linux».
"""

from __future__ import annotations

import json
import logging

from . import schemas, tools

logger = logging.getLogger(__name__)

TOOLSET = "jarvis_linux"


def _load_settings(ctx) -> dict:
    out = {}
    for key, default in (
        ("allow_raw_shell", False),
        ("screenshot_dir", ""),
        ("default_player", "auto"),
        ("hud_url", "http://127.0.0.1:8765"),
    ):
        try:
            out[key] = ctx.get_config(key, default=default)
        except Exception:
            out[key] = default
    return out


def register(ctx) -> None:
    settings = _load_settings(ctx)
    tools.configure(**settings)

    for schema in schemas.ALL_SCHEMAS:
        name = schema["name"]
        handler = tools.HANDLERS[name]
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler)

    def cmd_screen(raw: str) -> str:
        """/screen — скриншот + краткий отчёт о том, где сохранён."""
        res = json.loads(tools.linux_screenshot({"mode": "front_window" if "окно" in raw or "window" in raw else "screen"}))
        return f"Скриншот: {res.get('path')}" if res.get("success") else f"Ошибка: {res.get('error')}"

    def cmd_vol(raw: str) -> str:
        """/vol 30 | /vol mute | /vol up"""
        raw = raw.strip().lower()
        if raw.isdigit():
            r = tools.linux_volume({"action": "set", "level": int(raw)})
        elif raw in ("mute", "unmute", "up", "down", "get"):
            r = tools.linux_volume({"action": raw})
        else:
            return "Использование: /vol <0-100> | up | down | mute | unmute | get"
        return r

    def cmd_sysinfo(raw: str) -> str:
        return tools.linux_system_info({"section": raw.strip() or "all"})

    def cmd_lock(raw: str) -> str:
        return tools.linux_power({"action": "lock"})

    for name, fn, desc in (
        ("screen", cmd_screen, "Скриншот экрана (или окна: /screen окно)"),
        ("vol", cmd_vol, "Громкость: /vol 30 | up | down | mute"),
        ("sysinfo", cmd_sysinfo, "Сводка о системе"),
        ("lock", cmd_lock, "Заблокировать экран"),
    ):
        try:
            ctx.register_command(name, fn, description=desc)
        except Exception as e:
            logger.debug("register_command(%s) недоступен: %s", name, e)

    logger.info("jarvis-linux: зарегистрировано %d инструментов", len(schemas.ALL_SCHEMAS))
