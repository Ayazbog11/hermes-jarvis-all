"""
Схемы инструментов плагина jarvis-windows (зеркало jarvis-macos для Windows).

Это то, что «видит» языковая модель: по описанию (description) она решает,
КОГДА вызывать инструмент, а по parameters — С КАКИМИ аргументами.
"""

# ─────────────────────────────── Приложения ────────────────────────────────

WIN_APP = {
    "name": "win_app",
    "description": (
        "Управление приложениями Windows: открыть, закрыть, свернуть, показать, "
        "переключиться, получить список запущенных. Используй для фраз вроде "
        "«открой Блокнот», «закрой Telegram», «какие приложения запущены»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["open", "quit", "force_quit", "hide", "activate", "list_running", "is_running"],
                "description": "Действие над приложением",
            },
            "app": {
                "type": "string",
                "description": "Имя приложения или .exe (notepad, chrome, Telegram, «Проводник»…). "
                               "Не нужно для list_running.",
            },
        },
        "required": ["action"],
    },
}

WIN_OPEN = {
    "name": "win_open",
    "description": (
        "Открыть URL, файл или папку стандартным приложением (аналог `start`). "
        "Примеры: «открой youtube.com», «открой папку Загрузки», «открой этот PDF»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "URL (https://…), путь к файлу/папке или имя стандартной папки (Downloads, Desktop, Documents)"},
            "app": {"type": "string", "description": "Необязательно: открыть конкретным приложением (например, 'chrome')"},
        },
        "required": ["target"],
    },
}

WIN_SEARCH = {
    "name": "win_search",
    "description": "Поиск файлов на диске (Windows Search индекс через `Get-ChildItem`/COM, либо `everything` если установлен). Примеры: «найди презентацию про бюджет», «где файл отчёт.xlsx».",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Поисковый запрос (имя файла, поддерживает *)"},
            "limit": {"type": "integer", "description": "Максимум результатов (по умолчанию 20)", "default": 20},
            "only_dir": {"type": "string", "description": "Ограничить поиск папкой (путь); по умолчанию — профиль пользователя"},
        },
        "required": ["query"],
    },
}

WIN_EXPLORER = {
    "name": "win_explorer",
    "description": "Показать файл/папку в Проводнике, открыть Корзину, очистить Корзину (с подтверждением пользователя!).",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["reveal", "open_trash", "empty_trash", "new_window"]},
            "path": {"type": "string", "description": "Путь для reveal/new_window"},
        },
        "required": ["action"],
    },
}

# ─────────────────────────────── Система ───────────────────────────────────

WIN_VOLUME = {
    "name": "win_volume",
    "description": (
        "Громкость Windows: установить (0–100), прибавить/убавить, включить/выключить звук, узнать текущую. "
        "Примеры: «сделай громкость 30», «потише», «выключи звук»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set", "up", "down", "mute", "unmute", "toggle_mute", "get"]},
            "level": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Уровень для set / шаг для up|down (по умолчанию 10)"},
        },
        "required": ["action"],
    },
}

WIN_BRIGHTNESS = {
    "name": "win_brightness",
    "description": "Яркость экрана: установить (0–100), прибавить/убавить (через WMI WmiMonitorBrightnessMethods; на настольных мониторах без DDC может быть недоступно).",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set", "up", "down", "get"]},
            "level": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Уровень для set (0–100) или число шагов для up/down"},
        },
        "required": ["action"],
    },
}

WIN_DARK_MODE = {
    "name": "win_dark_mode",
    "description": "Тёмная тема Windows (Apps + System): включить, выключить, переключить, узнать состояние.",
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["on", "off", "toggle", "get"]}},
        "required": ["action"],
    },
}

WIN_POWER = {
    "name": "win_power",
    "description": (
        "Питание и блокировка: заблокировать экран, усыпить (sleep), выключить экран, перезагрузить, выключить ПК, "
        "запустить заставку. Для restart/shutdown/logout ОБЯЗАТЕЛЬНО сначала переспроси пользователя."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["lock", "sleep", "display_sleep", "screensaver", "restart", "shutdown", "logout", "hibernate"]},
            "confirmed": {"type": "boolean", "description": "true только если пользователь явно подтвердил restart/shutdown/logout/hibernate", "default": False},
        },
        "required": ["action"],
    },
}

WIN_WIFI = {
    "name": "win_wifi",
    "description": "Wi-Fi: включить, выключить, узнать текущую сеть/состояние (через netsh).",
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["on", "off", "status"]}},
        "required": ["action"],
    },
}

WIN_BLUETOOTH = {
    "name": "win_bluetooth",
    "description": "Bluetooth: включить, выключить, статус, список сопряжённых устройств.",
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["on", "off", "status", "devices"]}},
        "required": ["action"],
    },
}

WIN_BATTERY = {
    "name": "win_battery",
    "description": "Состояние батареи ноутбука: заряд в процентах, заряжается ли, оставшееся время (WMI/powercfg). На настольном ПК без батареи вернёт соответствующее сообщение.",
    "parameters": {"type": "object", "properties": {}},
}

WIN_SYSTEM_INFO = {
    "name": "win_system_info",
    "description": "Сводка о системе: модель ПК, версия Windows, CPU, память, диск, аптайм, IP-адрес, топ процессов по CPU.",
    "parameters": {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["all", "hardware", "memory", "disk", "network", "processes", "uptime"],
                "default": "all",
            }
        },
    },
}

# ─────────────────────────────── Медиа ─────────────────────────────────────

WIN_MEDIA = {
    "name": "win_media",
    "description": (
        "Управление медиа (Spotify или системный медиаплеер через виртуальные клавиши мультимедиа): play, pause, next, "
        "previous, что играет, включить трек/плейлист по названию (Spotify). Примеры: «включи музыку», «следующий трек», "
        "«что сейчас играет», «включи плейлист Chill»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["play", "pause", "toggle", "next", "previous", "now_playing", "play_track", "play_playlist"]},
            "query": {"type": "string", "description": "Название трека/исполнителя/плейлиста для play_track / play_playlist (Spotify)"},
            "player": {"type": "string", "enum": ["auto", "media", "spotify"], "default": "auto"},
        },
        "required": ["action"],
    },
}

WIN_SAY = {
    "name": "win_say",
    "description": (
        "Произнести текст системным голосом Windows (SAPI System.Speech) или ОСТАНОВИТЬ речь. НЕ используй для обычных "
        "ответов — их уже озвучивает TTS Hermes, и получится дубль. action=stop — «замолчи», «стоп», «хватит»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["say", "stop"], "default": "say"},
            "text": {"type": "string"},
            "voice": {"type": "string", "description": "Имя установленного голоса SAPI (например Microsoft Irina Desktop). По умолчанию — системный."},
            "rate": {"type": "integer", "description": "Скорость речи -10..10"},
        },
        "required": ["text"],
    },
}

WIN_NOTIFY = {
    "name": "win_notify",
    "description": "Показать всплывающее Toast-уведомление Windows (Центр уведомлений).",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "message": {"type": "string"},
            "subtitle": {"type": "string"},
            "sound": {"type": "boolean", "default": True},
        },
        "required": ["title", "message"],
    },
}

WIN_SCREENSHOT = {
    "name": "win_screenshot",
    "description": (
        "Сделать скриншот экрана (весь экран или активное окно) и вернуть путь к PNG. "
        "После этого можно вызвать vision_analyze с этим путём, чтобы «посмотреть» на экран. "
        "Примеры: «что у меня на экране?», «сделай скриншот»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["screen", "front_window"], "default": "screen"},
            "display": {"type": "integer", "description": "Номер дисплея (1 — основной)", "default": 1},
        },
    },
}

WIN_CAMERA_SNAP = {
    "name": "win_camera_snap",
    "description": "Сделать снимок с веб-камеры (через ffmpeg dshow, если установлен). Возвращает путь к JPG — далее vision_analyze.",
    "parameters": {"type": "object", "properties": {"warmup": {"type": "number", "default": 1.0, "description": "Секунды прогрева камеры"}}},
}

WIN_WALLPAPER = {
    "name": "win_wallpaper",
    "description": "Сменить обои рабочего стола на указанный файл изображения.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
}

# ─────────────────────────────── Продуктивность ────────────────────────────

WIN_CALENDAR = {
    "name": "win_calendar",
    "description": (
        "Календарь Outlook (если установлен и настроен) или Windows Calendar App: события на сегодня/завтра/дату, "
        "создать событие. Примеры: «что у меня сегодня по плану», «поставь встречу завтра в 15:00 на час». "
        "Если Outlook не настроен — вернёт понятную ошибку."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["today", "tomorrow", "on_date", "create"]},
            "date": {"type": "string", "description": "Дата YYYY-MM-DD для on_date/create"},
            "title": {"type": "string", "description": "Название события (create)"},
            "start_time": {"type": "string", "description": "HH:MM (create)"},
            "duration_min": {"type": "integer", "default": 60},
            "calendar": {"type": "string", "description": "Имя календаря Outlook; по умолчанию — основной"},
        },
        "required": ["action"],
    },
}

WIN_REMINDERS = {
    "name": "win_reminders",
    "description": "Напоминания: локальный список (хранится в базе знаний JARVIS) — список активных, добавить (с датой/временем), отметить выполненным. «Напомни завтра в 9 позвонить маме».",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "complete"]},
            "title": {"type": "string"},
            "due": {"type": "string", "description": "YYYY-MM-DD HH:MM (необязательно)"},
            "list_name": {"type": "string", "description": "Имя списка напоминаний; по умолчанию — список по умолчанию"},
        },
        "required": ["action"],
    },
}

WIN_NOTES = {
    "name": "win_notes",
    "description": "Заметки: создать, найти по тексту, показать содержимое (файлы .md в $HERMES_HOME/jarvis/notes — простой кроссплатформенный аналог Apple Notes). «Запиши в заметки: …».",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "search", "read"]},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "query": {"type": "string"},
            "folder": {"type": "string", "description": "Подпапка заметок (по умолчанию корень)"},
        },
        "required": ["action"],
    },
}

WIN_CLIPBOARD = {
    "name": "win_clipboard",
    "description": "Буфер обмена: прочитать текст из буфера или положить текст в буфер.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get", "set"]},
            "text": {"type": "string"},
        },
        "required": ["action"],
    },
}

WIN_TYPE = {
    "name": "win_type",
    "description": (
        "Напечатать текст в активное окно или нажать сочетание клавиш (через SendKeys). "
        "Примеры: «напечатай …», «нажми ctrl+s»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["type_text", "keystroke"]},
            "text": {"type": "string", "description": "Текст для type_text или клавиша для keystroke (например 's', 'enter', 'tab', 'space')"},
            "modifiers": {
                "type": "array",
                "items": {"type": "string", "enum": ["ctrl", "alt", "shift", "win"]},
                "description": "Модификаторы для keystroke",
            },
        },
        "required": ["action", "text"],
    },
}

WIN_WINDOW = {
    "name": "win_window",
    "description": "Окна: развернуть на весь экран, свернуть, расположить активное окно слева/справа/по центру (Snap), список окон приложения.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["maximize", "minimize", "left_half", "right_half", "center", "list"]},
            "app": {"type": "string", "description": "Приложение (по умолчанию — активное)"},
        },
        "required": ["action"],
    },
}

WIN_SHORTCUT = {
    "name": "win_shortcut",
    "description": "Запустить скрипт из папки $HERMES_HOME/jarvis/shortcuts (.ps1/.bat) по имени — аналог macOS Shortcuts, при необходимости передав текст на вход. Также умеет перечислить доступные.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["run", "list"], "default": "run"},
            "name": {"type": "string", "description": "Имя скрипта (без расширения)"},
            "input": {"type": "string", "description": "Текст на вход скрипта (передаётся первым аргументом)"},
        },
    },
}

WIN_CONTACTS = {
    "name": "win_contacts",
    "description": (
        "Контакты Outlook (если настроен): search — найти человека по имени (email, телефон, организация); "
        "list — контакты с организацией. Персональные данные — не передавай наружу без нужды."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "list"], "default": "search"},
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["action"],
    },
}

WIN_FOCUS = {
    "name": "win_focus",
    "description": (
        "Режим фокуса Windows («Focus Assist» / «Не беспокоить»): get — активен ли; set — включить/выключить "
        "(приоритетный список или полная тишина). Режим JARVIS синхронизируется автоматически."
    ),
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["get", "set"], "default": "get"}, "name": {"type": "string", "description": "on | off | priority"}},
        "required": ["action"],
    },
}

WIN_FILE_MANAGE = {
    "name": "win_file_manage",
    "description": (
        "Файловые операции на Windows: trash (в Корзину — единственный способ удаления), rename, move, mkdir, list (содержимое папки), "
        "info. Понимает алиасы папок: загрузки, рабочий стол, документы. Для чтения/записи содержимого используй file-инструменты Hermes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["trash", "rename", "move", "mkdir", "list", "info"]},
            "path": {"type": "string", "description": "Путь или алиас (~/Downloads, «рабочий стол»)"},
            "new_name": {"type": "string", "description": "Для rename"},
            "destination": {"type": "string", "description": "Папка назначения для move"},
            "limit": {"type": "integer", "default": 30},
        },
        "required": ["action"],
    },
}

WIN_POWERSHELL = {
    "name": "win_powershell",
    "description": (
        "Выполнить произвольный PowerShell-скрипт. ВКЛЮЧАЕТСЯ настройкой allow_raw_powershell. "
        "Используй только когда ни один специализированный win_* инструмент не подходит."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "script": {"type": "string"},
        },
        "required": ["script"],
    },
}

ALL_SCHEMAS = [
    WIN_APP, WIN_OPEN, WIN_SEARCH, WIN_EXPLORER,
    WIN_VOLUME, WIN_BRIGHTNESS, WIN_DARK_MODE, WIN_POWER, WIN_WIFI, WIN_BLUETOOTH, WIN_BATTERY, WIN_SYSTEM_INFO,
    WIN_MEDIA, WIN_SAY, WIN_NOTIFY, WIN_SCREENSHOT, WIN_CAMERA_SNAP, WIN_WALLPAPER, WIN_FILE_MANAGE, WIN_CONTACTS, WIN_FOCUS,
    WIN_CALENDAR, WIN_REMINDERS, WIN_NOTES, WIN_CLIPBOARD, WIN_TYPE, WIN_WINDOW, WIN_SHORTCUT, WIN_POWERSHELL,
]
