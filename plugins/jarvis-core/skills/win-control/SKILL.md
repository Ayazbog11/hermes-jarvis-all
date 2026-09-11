---
name: win-control
description: Как JARVIS управляет Windows — выбор инструмента, подтверждения, права администратора
version: 1.0.0
platforms: [windows]
metadata:
  hermes:
    tags: [jarvis, windows, automation]
    category: devops
---

# Управление Windows

## When to Use
Любая просьба, затрагивающая компьютер: приложения, звук, экран, окна, файлы, музыка, календарь,
заметки, напоминания, буфер обмена, питание.

## Decision table
| Просьба | Инструмент |
|---|---|
| открой/закрой приложение | `win_app` |
| открой сайт / файл / папку | `win_open` |
| найди файл | `win_search` → потом `win_explorer reveal` |
| громче/тише/звук | `win_volume` |
| ярче/темнее | `win_brightness` (может быть недоступно на мониторах без DDC/CI) |
| тёмная тема | `win_dark_mode` |
| заблокируй / усыпи / выключи | `win_power` (restart/shutdown/logout/hibernate — только после подтверждения!) |
| музыка | `win_media` |
| что на экране? | `win_screenshot` → `vision_analyze(path)` |
| что видит камера? | `win_camera_snap` → `vision_analyze(path)` |
| планы / встречи | `jarvis_calendar` (Google Calendar — единый для всех ОС, не требует Outlook; настройка: `jarvis calendar setup`) |
| напомни | `win_reminders` (локальный список) или `jarvis_timer` (короткие интервалы) |
| запиши / заметка | `win_notes` |
| скопируй / вставь | `win_clipboard` |
| напечатай / нажми | `win_type` |
| окно влево/вправо/на весь экран | `win_window` |
| именованный скрипт-автоматизация | `win_shortcut` |
| всё остальное про Windows | `terminal` (безопасные команды) или `win_powershell` (если включён) |

## Procedure
1. Выбери самый специализированный инструмент из таблицы. `terminal` — только если ничего не подходит.
2. Для необратимых действий (выключение, очистка корзины, удаление файлов) — сначала `clarify`/переспроси.
3. После действия отвечай коротко: «Готово, Блокнот открыт», без пересказа JSON.
4. Если инструмент вернул `error` про «отказано в доступе» — объясни пользователю в одну фразу: нужно запустить
   JARVIS/терминал «от имени администратора», либо разрешить выполнение сценариев PowerShell
   (`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`).

## Pitfalls
- Имена приложений для `win_app` — как исполняемый файл без `.exe` (notepad, chrome, Telegram) или как он отображается в списке процессов.
- `win_type` печатает в АКТИВНОЕ окно — сначала `win_app activate` нужного приложения.
- `jarvis_calendar` работает через Google Calendar (не Outlook) — если `needs_setup=true`, объясни пользователю, что нужно один раз выполнить `jarvis calendar setup` в терминале (откроется браузер для входа в Google). `win_contacts` по-прежнему требует настроенный классический Outlook (COM) — контакты в Google Calendar не переносились.
- Bluetooth radio on/off штатно недоступен из PowerShell (только статус и список устройств) — Windows не даёт это делать без сторонних утилит, в отличие от `blueutil` на macOS.
- Focus Assist (`win_focus`) не имеет документированного публичного API для чтения/записи статуса — сообщи пользователю об ограничении, если он спрашивает.
- Не вызывай `win_say`, если TTS Hermes уже включён — будет двойной голос.

## Verification
Инструмент вернул `"success": true`; при необходимости подтверди результат (`win_app is_running`, `win_volume get`).
