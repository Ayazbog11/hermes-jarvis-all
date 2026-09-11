"""
Схемы инструментов плагина jarvis-linux (зеркало jarvis-macos/jarvis-windows для Linux).

Это то, что «видит» языковая модель: по описанию (description) она решает,
КОГДА вызывать инструмент, а по parameters — С КАКИМИ аргументами.
"""

# ─────────────────────────────── Приложения ────────────────────────────────

LINUX_APP = {
    "name": "linux_app",
    "description": (
        "Управление приложениями Linux: открыть, закрыть, свернуть, переключиться, получить список "
        "запущенных. Используй для фраз вроде «открой Firefox», «закрой Telegram», «какие приложения запущены»."
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
                "description": "Имя приложения/бинарника (firefox, code, telegram-desktop…). Не нужно для list_running.",
            },
        },
        "required": ["action"],
    },
}

LINUX_OPEN = {
    "name": "linux_open",
    "description": (
        "Открыть URL, файл или папку стандартным приложением (xdg-open). "
        "Примеры: «открой youtube.com», «открой папку Загрузки», «открой этот PDF»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "URL (https://…), путь к файлу/папке или имя стандартной папки (Downloads, Desktop, Documents)"},
        },
        "required": ["target"],
    },
}

LINUX_SEARCH = {
    "name": "linux_search",
    "description": "Поиск файлов на диске (locate/plocate с индексом, либо find как фолбэк). Примеры: «найди презентацию про бюджет», «где файл отчёт.xlsx».",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Поисковый запрос (имя файла, поддерживает *)"},
            "limit": {"type": "integer", "description": "Максимум результатов (по умолчанию 20)", "default": 20},
            "only_dir": {"type": "string", "description": "Ограничить поиск папкой (путь); по умолчанию — домашний каталог"},
        },
        "required": ["query"],
    },
}

LINUX_FILES = {
    "name": "linux_files",
    "description": "Открыть файловый менеджер: показать файл/папку, открыть корзину (через Trash freedesktop API), очистить корзину.",
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

LINUX_VOLUME = {
    "name": "linux_volume",
    "description": (
        "Громкость (PipeWire/PulseAudio через pactl, либо ALSA через amixer): установить (0–100), "
        "прибавить/убавить, включить/выключить звук, узнать текущую. Примеры: «сделай громкость 30», «потише», «выключи звук»."
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

LINUX_BRIGHTNESS = {
    "name": "linux_brightness",
    "description": "Яркость экрана: установить (0–100), прибавить/убавить (через brightnessctl или xbacklight).",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set", "up", "down", "get"]},
            "level": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Уровень для set (0–100) или число шагов для up/down"},
        },
        "required": ["action"],
    },
}

LINUX_DARK_MODE = {
    "name": "linux_dark_mode",
    "description": "Тёмная тема (GNOME/GTK через gsettings; для KDE — подсказка использовать плазма-настройки): включить, выключить, переключить, узнать состояние.",
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["on", "off", "toggle", "get"]}},
        "required": ["action"],
    },
}

LINUX_POWER = {
    "name": "linux_power",
    "description": (
        "Питание и блокировка: заблокировать экран (loginctl/xdg-screensaver), усыпить, перезагрузить, выключить ПК, "
        "запустить заставку. Для restart/shutdown ОБЯЗАТЕЛЬНО сначала переспроси пользователя."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["lock", "sleep", "screensaver", "restart", "shutdown", "logout", "hibernate"]},
            "confirmed": {"type": "boolean", "description": "true только если пользователь явно подтвердил restart/shutdown/logout/hibernate", "default": False},
        },
        "required": ["action"],
    },
}

LINUX_PROCESS = {
    "name": "linux_process",
    "description": (
        "Процессы Linux: list — топ процессов по CPU/памяти; find — найти процесс по имени; "
        "kill — завершить процесс по PID или имени (аналог htop/System Monitor). Используй для «завис Firefox, "
        "закрой его насильно», «что грузит процессор», «сколько памяти ест эта программа». Для kill "
        "ОБЯЗАТЕЛЬНО сначала переспроси пользователя и передай confirmed=true — завершение процесса может "
        "привести к потере несохранённых данных."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "find", "kill"]},
            "sort_by": {"type": "string", "enum": ["cpu", "memory"], "default": "cpu", "description": "Для list"},
            "limit": {"type": "integer", "default": 12, "description": "Для list"},
            "name": {"type": "string", "description": "Имя процесса (для find/kill по имени)"},
            "pid": {"type": "integer", "description": "PID (для kill по конкретному процессу)"},
            "force": {"type": "boolean", "default": False, "description": "Принудительное завершение (kill -9 / SIGKILL)"},
            "confirmed": {"type": "boolean", "default": False, "description": "true только если пользователь явно подтвердил kill"},
        },
        "required": ["action"],
    },
}

LINUX_WIFI = {
    "name": "linux_wifi",
    "description": "Wi-Fi: включить, выключить, узнать текущую сеть/состояние (через nmcli, NetworkManager).",
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["on", "off", "status"]}},
        "required": ["action"],
    },
}

LINUX_BLUETOOTH = {
    "name": "linux_bluetooth",
    "description": "Bluetooth: включить, выключить, статус, список сопряжённых устройств (через bluetoothctl, BlueZ).",
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["on", "off", "status", "devices"]}},
        "required": ["action"],
    },
}

LINUX_BATTERY = {
    "name": "linux_battery",
    "description": "Состояние батареи ноутбука: заряд в процентах, заряжается ли (upower / /sys/class/power_supply). На настольном ПК без батареи вернёт соответствующее сообщение.",
    "parameters": {"type": "object", "properties": {}},
}

LINUX_SYSTEM_INFO = {
    "name": "linux_system_info",
    "description": "Сводка о системе: дистрибутив/ядро, CPU, память, диск, аптайм, IP-адрес, топ процессов по CPU.",
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

LINUX_MEDIA = {
    "name": "linux_media",
    "description": (
        "Управление медиа через MPRIS (playerctl — работает со Spotify, VLC, Firefox, браузерами и т.п.): play, pause, "
        "next, previous, что играет. Примеры: «включи музыку», «следующий трек», «что сейчас играет»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["play", "pause", "toggle", "next", "previous", "now_playing"]},
            "player": {"type": "string", "description": "Имя плеера MPRIS (auto — первый найденный, или подстрока имени, например 'spotify')", "default": "auto"},
        },
        "required": ["action"],
    },
}

LINUX_SAY = {
    "name": "linux_say",
    "description": (
        "Произнести текст системным голосом (espeak-ng/spd-say/piper) или ОСТАНОВИТЬ речь. НЕ используй для обычных "
        "ответов — их уже озвучивает TTS Hermes, и получится дубль. action=stop — «замолчи», «стоп», «хватит»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["say", "stop"], "default": "say"},
            "text": {"type": "string"},
            "voice": {"type": "string", "description": "Голос espeak-ng (например ru, en-us). По умолчанию — системный/русский."},
        },
        "required": ["text"],
    },
}

LINUX_NOTIFY = {
    "name": "linux_notify",
    "description": "Показать всплывающее уведомление рабочего стола (notify-send, freedesktop notifications).",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "message": {"type": "string"},
            "urgency": {"type": "string", "enum": ["low", "normal", "critical"], "default": "normal"},
        },
        "required": ["title", "message"],
    },
}

LINUX_SCREENSHOT = {
    "name": "linux_screenshot",
    "description": (
        "Сделать скриншот экрана (весь экран или активное окно) и вернуть путь к PNG "
        "(grim на Wayland; scrot/gnome-screenshot/spectacle/import на X11). "
        "После этого можно вызвать vision_analyze с этим путём, чтобы «посмотреть» на экран. "
        "Примеры: «что у меня на экране?», «сделай скриншот»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["screen", "front_window"], "default": "screen"},
        },
    },
}

LINUX_CAMERA_SNAP = {
    "name": "linux_camera_snap",
    "description": "Сделать снимок с веб-камеры (через ffmpeg /dev/video0, если установлен). Возвращает путь к JPG — далее vision_analyze.",
    "parameters": {"type": "object", "properties": {"warmup": {"type": "number", "default": 1.0, "description": "Секунды прогрева камеры"}, "device": {"type": "string", "default": "/dev/video0"}}},
}

LINUX_WALLPAPER = {
    "name": "linux_wallpaper",
    "description": "Сменить обои рабочего стола на указанный файл изображения (GNOME/gsettings; для других DE — подсказка).",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
}

# ─────────────────────────────── Продуктивность ────────────────────────────

LINUX_CALENDAR = {
    "name": "linux_calendar",
    "description": (
        "Календарь через khal (CLI поверх CalDAV/vdirsyncer), если установлен и настроен: события на сегодня/завтра/дату, "
        "создать событие. Примеры: «что у меня сегодня по плану», «поставь встречу завтра в 15:00 на час». "
        "Если khal не настроен — вернёт понятную ошибку и предложит linux_reminders как альтернативу."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["today", "tomorrow", "on_date", "create"]},
            "date": {"type": "string", "description": "Дата YYYY-MM-DD для on_date/create"},
            "title": {"type": "string", "description": "Название события (create)"},
            "start_time": {"type": "string", "description": "HH:MM (create)"},
            "duration_min": {"type": "integer", "default": 60},
        },
        "required": ["action"],
    },
}

LINUX_REMINDERS = {
    "name": "linux_reminders",
    "description": "Напоминания: локальный список (JSON-файл) — список активных, добавить (с датой/временем), отметить выполненным. «Напомни завтра в 9 позвонить маме».",
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

LINUX_NOTES = {
    "name": "linux_notes",
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

LINUX_CLIPBOARD = {
    "name": "linux_clipboard",
    "description": "Буфер обмена: прочитать текст из буфера или положить текст в буфер (xclip/xsel на X11, wl-clipboard на Wayland).",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get", "set"]},
            "text": {"type": "string"},
        },
        "required": ["action"],
    },
}

LINUX_TYPE = {
    "name": "linux_type",
    "description": (
        "Напечатать текст в активное окно или нажать сочетание клавиш (xdotool на X11, ydotool на Wayland). "
        "Примеры: «напечатай …», «нажми ctrl+s»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["type_text", "keystroke"]},
            "text": {"type": "string", "description": "Текст для type_text или клавиша для keystroke (например 's', 'Return', 'Tab', 'space')"},
            "modifiers": {
                "type": "array",
                "items": {"type": "string", "enum": ["ctrl", "alt", "shift", "super"]},
                "description": "Модификаторы для keystroke",
            },
        },
        "required": ["action", "text"],
    },
}

LINUX_WINDOW = {
    "name": "linux_window",
    "description": "Окна: развернуть на весь экран, свернуть, расположить активное окно слева/справа/по центру, список окон (wmctrl/xdotool, X11).",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["maximize", "minimize", "left_half", "right_half", "center", "list"]},
            "app": {"type": "string", "description": "Приложение (по умолчанию — активное)"},
        },
        "required": ["action"],
    },
}

LINUX_SHORTCUT = {
    "name": "linux_shortcut",
    "description": "Запустить скрипт из папки $HERMES_HOME/jarvis/shortcuts (.sh/.py) по имени — аналог macOS Shortcuts, при необходимости передав текст на вход. Также умеет перечислить доступные.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["run", "list"], "default": "run"},
            "name": {"type": "string", "description": "Имя скрипта (без расширения)"},
            "input": {"type": "string", "description": "Текст на вход скрипта (передаётся первым аргументом)"},
        },
    },
}

LINUX_FOCUS = {
    "name": "linux_focus",
    "description": (
        "Режим фокуса «Не беспокоить» (GNOME: org.gnome.desktop.notifications show-banners; на других окружениях — "
        "ограниченная поддержка): get — активен ли; set — включить/выключить. Режим JARVIS синхронизируется автоматически там, где доступно."
    ),
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["get", "set"], "default": "get"}, "name": {"type": "string", "description": "on | off"}},
        "required": ["action"],
    },
}

LINUX_FILE_MANAGE = {
    "name": "linux_file_manage",
    "description": (
        "Файловые операции на Linux: trash (в Корзину через gio trash/trash-cli — единственный способ удаления), rename, "
        "move, mkdir, list (содержимое папки), info. Понимает алиасы папок: загрузки, рабочий стол, документы."
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

LINUX_SHELL = {
    "name": "linux_shell",
    "description": (
        "Выполнить произвольную команду shell (bash). ВКЛЮЧАЕТСЯ настройкой allow_raw_shell. "
        "Используй только когда ни один специализированный linux_* инструмент не подходит."
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
    LINUX_APP, LINUX_OPEN, LINUX_SEARCH, LINUX_FILES,
    LINUX_VOLUME, LINUX_BRIGHTNESS, LINUX_DARK_MODE, LINUX_POWER, LINUX_PROCESS, LINUX_WIFI, LINUX_BLUETOOTH, LINUX_BATTERY, LINUX_SYSTEM_INFO,
    LINUX_MEDIA, LINUX_SAY, LINUX_NOTIFY, LINUX_SCREENSHOT, LINUX_CAMERA_SNAP, LINUX_WALLPAPER, LINUX_FILE_MANAGE, LINUX_FOCUS,
    LINUX_CALENDAR, LINUX_REMINDERS, LINUX_NOTES, LINUX_CLIPBOARD, LINUX_TYPE, LINUX_WINDOW, LINUX_SHORTCUT, LINUX_SHELL,
]
