---
name: linux-control
description: Как JARVIS управляет Linux — выбор инструмента, подтверждения, зависимость от рабочего окружения (X11/Wayland/GNOME/KDE)
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [jarvis, linux, automation]
    category: devops
---

# Управление Linux

## When to Use
Любая просьба, затрагивающая компьютер: приложения, звук, экран, окна, файлы, музыка, календарь,
заметки, напоминания, буфер обмена, питание, Wi-Fi/Bluetooth.

## Decision table
| Просьба | Инструмент |
|---|---|
| открой/закрой приложение | `linux_app` |
| открой сайт / файл / папку | `linux_open` |
| найди файл | `linux_search` → потом `linux_files reveal` |
| громче/тише/звук | `linux_volume` (PipeWire/PulseAudio через `pactl`, фолбэк `amixer`) |
| ярче/темнее | `linux_brightness` (нужен `brightnessctl`; ноутбучные панели без стандартного backlight могут быть недоступны) |
| тёмная тема | `linux_dark_mode` (только GNOME/GTK через `gsettings`; на KDE/XFCE сообщи об ограничении) |
| заблокируй / усыпи / выключи | `linux_power` (restart/shutdown/logout/hibernate — только после подтверждения!) |
| Wi-Fi вкл/выкл/статус | `linux_wifi` (нужен NetworkManager/`nmcli`) |
| Bluetooth вкл/выкл/устройства | `linux_bluetooth` (нужен BlueZ/`bluetoothctl`) |
| музыка | `linux_media` (через MPRIS/`playerctl` — работает с любым плеером, поддерживающим MPRIS: Spotify, VLC, mpv, browsers) |
| что на экране? | `linux_screenshot` → `vision_analyze(path)` (Wayland: `grim`; X11: `scrot`/`import`; DE со своим инструментом: `gnome-screenshot`/`spectacle`) |
| что видит камера? | `linux_camera_snap` → `vision_analyze(path)` |
| планы / встречи | `linux_calendar` (нужен `khal`, настроенный на CalDAV — опционально, многие системы без него) |
| напомни | `linux_reminders` (локальный список) или `jarvis_timer` (короткие интервалы) |
| запиши / заметка | `linux_notes` |
| скопируй / вставь | `linux_clipboard` (X11: `xclip`; Wayland: `wl-clipboard`) |
| напечатай / нажми | `linux_type` (нужен `xdotool` на X11; на Wayland — ограниченно, только через `ydotool` с запущенным демоном) |
| окно влево/вправо/на весь экран | `linux_window` (нужен `wmctrl`, для half/center — дополнительно `xdotool`; на чистом Wayland без совместимого композитора может не сработать) |
| именованный скрипт-автоматизация | `linux_shortcut` |
| всё остальное про Linux | `terminal` (безопасные команды) или `linux_shell` (если включён `allow_raw_shell`) |

## Procedure
1. Выбери самый специализированный инструмент из таблицы. `terminal`/`linux_shell` — только если ничего не подходит.
2. Для необратимых действий (выключение, очистка корзины, удаление файлов) — сначала `clarify`/переспроси.
3. После действия отвечай коротко: «Готово, громкость 40%», без пересказа JSON.
4. Если инструмент вернул ошибку «Нужен <утилита>» — сообщи пользователю одной фразой, какой пакет поставить
   (обычно `sudo apt install <пакет>` / `dnf install` / `pacman -S` в зависимости от дистрибутива — см. подсказку
   в тексте ошибки) и что `jarvis selftest --fix` покажет полный список отсутствующих зависимостей.

## Pitfalls
- Linux — не единая платформа: набор рабочих столов (GNOME/KDE/XFCE/Sway/…) и протоколов (X11/Wayland) сильно
  влияет на то, что вообще возможно. Некоторые инструменты (тёмная тема, «Не беспокоить», часть `linux_type`)
  работают только на GNOME/X11 — если действие не удалось, объясни ограничение, а не притворяйся, что всё ок.
- `linux_type`/`linux_window` (left_half/right_half/center) требуют `xdotool`, которого на чистом Wayland-сеансе
  (например GNOME на Wayland) обычно нет — там доступен только `wmctrl`-уровень (list/activate/maximize/minimize).
- Имена приложений для `linux_app` — как исполняемый файл (firefox, code, telegram-desktop) или заголовок окна,
  который видно в `wmctrl -l`.
- `linux_calendar`/`linux_reminders` без настроенного `khal` работают только с локальным списком напоминаний —
  не выдумывай события, которых нет.
- Bluetooth/Wi-Fi управление зависит от NetworkManager/BlueZ; на серверных/минимальных установках их может не быть —
  тогда сообщи, что это не входит в базовую установку.
- Не вызывай `linux_say`, если TTS Hermes уже включён — будет двойной голос.
- Удаление файлов через `linux_file_manage trash` уходит во freedesktop Корзину (`gio trash`/`trash-put`), а не
  удаляется безвозвратно — это ожидаемое и безопасное поведение.

## Verification
Инструмент вернул `"success": true`; при необходимости подтверди результат (`linux_app is_running`, `linux_volume get`).
