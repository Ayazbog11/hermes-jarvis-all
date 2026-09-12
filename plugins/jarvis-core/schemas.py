"""Схемы инструментов ядра JARVIS."""

JARVIS_VOICE_NOTE = {
    "name": "jarvis_voice_note",
    "description": (
        "Создать голосовое сообщение (аудиофайл) из текста, используя тот же синтез речи, что и HUD "
        "(edge-tts / системный голос). Возвращает путь к файлу — передай его в jarvis_send_message "
        "(action=send_file) с тем же target, чтобы отправить голосовое в Telegram/Discord/и т.п. "
        "Используй, когда пользователь просит «отправь голосовое», «озвучь и пришли», «скажи это в чат голосом»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Текст, который нужно озвучить (до ~1500 символов)"},
        },
        "required": ["text"],
    },
}

JARVIS_WORKING_MEMORY = {
    "name": "jarvis_working_memory",
    "description": (
        "Кратковременная «рабочая память» на 1-3 дня (идея из alex2772/kuni: things_to_remember) — "
        "для незавершённых задач, обещаний и напоминаний «спроси завтра», которые ещё рано класть "
        "в постоянную базу знаний (brain_remember), но забывать между сообщениями нельзя. "
        "Записи сами исчезают через несколько дней (см. max_age_days), не засоряя память навсегда. "
        "action=add — записать; action=list — посмотреть активные записи; action=clear — очистить всё "
        "(используй, когда пользователь явно просит «забудь про текущие дела/задачи»)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list", "clear"], "default": "list"},
            "text": {"type": "string", "description": "Текст записи (для action=add) — короткая и самодостаточная фраза"},
            "max_age_days": {"type": "number", "description": "Для action=list — сколько дней назад ещё считать актуальным (по умолчанию 3)"},
        },
        "required": ["action"],
    },
}

JARVIS_HUD = {
    "name": "jarvis_hud",
    "description": (
        "Показать что-то на голографическом HUD JARVIS (веб-экран): текст/markdown, картинку (URL или путь), "
        "видео YouTube, веб-страницу (iframe) или очистить экран. Используй, когда пользователь говорит "
        "«покажи на экране», «выведи на HUD», «покажи видео про…», «очисти экран»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["show", "clear"], "default": "show"},
            "kind": {"type": "string", "enum": ["text", "markdown", "image", "video", "web", "chart"], "default": "text"},
            "title": {"type": "string"},
            "content": {
                "type": "string",
                "description": "Текст/markdown; URL картинки или локальный путь; URL YouTube/видео; URL страницы; "
                               "для chart — JSON вида {\"labels\":[...],\"values\":[...]}",
            },
            "position": {"type": "string", "enum": ["center", "left", "right"], "default": "center"},
            "ttl": {"type": "integer", "description": "Секунд до автоскрытия (0 — пока не очистят)", "default": 0},
        },
    },
}

JARVIS_TIMER = {
    "name": "jarvis_timer",
    "description": (
        "Таймеры и будильники: поставить на N минут или на время HH:MM, список, отмена. "
        "«Поставь таймер на 10 минут», «разбуди в 7:30», «отмени таймер»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set", "list", "cancel"]},
            "minutes": {"type": "number", "description": "Через сколько минут (для set)"},
            "at": {"type": "string", "description": "Время HH:MM (для set — будильник)"},
            "label": {"type": "string", "description": "Название таймера («чай», «созвон»)"},
        },
        "required": ["action"],
    },
}

JARVIS_MODE = {
    "name": "jarvis_mode",
    "description": (
        "Переключить режим JARVIS: normal (обычный), focus (не беспокоить, короткие ответы, без болтовни), "
        "night (тихий режим: тёмная тема, приглушённая громкость, короткие ответы), presentation (никаких уведомлений, "
        "не трогать окна). «Включи режим фокуса», «ночной режим», «обычный режим»."
    ),
    "parameters": {
        "type": "object",
        "properties": {"mode": {"type": "string", "enum": ["normal", "focus", "night", "presentation"]}},
        "required": ["mode"],
    },
}

JARVIS_UPDATE = {
    "name": "jarvis_update",
    "description": (
        "Самообновление JARVIS с GitHub. status — текущая версия и есть ли новая; check — проверить сейчас; "
        "apply — установить (делается бэкап, при ошибке автоматический откат, сервисы перезапускаются; "
        "ТОЛЬКО по явной просьбе пользователя и с confirmed=true); rollback — откатить последнее обновление; "
        "set_auto off|check|auto — режим автообновления; set_channel stable|main."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "check", "apply", "rollback", "set_auto", "set_channel"]},
            "value": {"type": "string", "description": "для set_auto: off|check|auto; для set_channel: stable|main"},
            "confirmed": {"type": "boolean", "default": False},
        },
        "required": ["action"],
    },
}

JARVIS_WEATHER = {
    "name": "jarvis_weather",
    "description": "Текущая погода и прогноз на сегодня для города (без API-ключа). «Какая погода?», «погода в Москве».",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "Город; по умолчанию — из настроек"}},
    },
}

JARVIS_CALENDAR = {
    "name": "jarvis_calendar",
    "description": (
        "Google Calendar — единый календарь JARVIS на macOS/Windows/Linux (не требует Outlook). "
        "today/tomorrow/on_date — список событий; create — создать событие; delete — удалить; "
        "status — настроен ли и авторизован ли календарь. Если status.authorized=false, "
        "объясни пользователю, что нужно один раз выполнить `jarvis calendar setup` в терминале "
        "(это открывает браузер для входа в Google-аккаунт) — сам инструмент авторизацию не запускает."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "today", "tomorrow", "on_date", "create", "delete"]},
            "date": {"type": "string", "description": "ISO-дата YYYY-MM-DD (для on_date)"},
            "title": {"type": "string", "description": "Название события (для create)"},
            "start_time": {"type": "string", "description": "Время начала HH:MM (для create), по умолчанию 12:00"},
            "duration_min": {"type": "integer", "description": "Длительность в минутах (для create), по умолчанию 60"},
            "location": {"type": "string", "description": "Место (для create)"},
            "description": {"type": "string", "description": "Описание/заметка (для create)"},
            "event_id": {"type": "string", "description": "ID события (для delete — сначала найдите его через today/on_date)"},
        },
        "required": ["action"],
    },
}

JARVIS_SEND_MESSAGE = {
    "name": "jarvis_send_message",
    "description": (
        "Отправить сообщение/файл/голосовое в мессенджер (Telegram, Discord, Slack, Signal, WhatsApp, SMS, "
        "Matrix и др.), которые настроены у пользователя в Hermes gateway. list — показать доступные цели "
        "(домашние каналы/чаты); send — отправить текст; send_file — отправить файл/фото/голосовое сообщение "
        "(caption необязателен). Используй, когда пользователь прямо просит «отправь мне в телеграм…», "
        "«пришли скриншот в дискорд…», «отправь голосовое …», «перешли это фото в Slack #канал…». "
        "ВАЖНО: если пользователь называет конкретный канал/чат/человека (не просто платформу), сначала "
        "вызови list, чтобы узнать точный target — не выдумывай chat_id/имя канала. Если платформа "
        "не настроена или Hermes недоступен, инструмент вернёт success=false с понятной причиной — "
        "объясни её пользователю, не пытайся угадать токен бота."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["send", "send_file", "list"], "default": "send"},
            "target": {
                "type": "string",
                "description": "Куда отправить: 'telegram' (домашний канал), 'telegram:-100123456789', "
                               "'discord:#ops', 'signal:+15551234567' и т.п. Для action=list — необязательный "
                               "фильтр по имени платформы (например 'telegram').",
            },
            "text": {"type": "string", "description": "Текст сообщения (для action=send)"},
            "subject": {"type": "string", "description": "Необязательный заголовок/тема перед текстом (для action=send)"},
            "path": {
                "type": "string",
                "description": "Локальный путь к файлу/фото/голосовому/документу (для action=send_file) — "
                               "например путь из mac_screenshot/win_screenshot/linux_screenshot, jarvis_image_generate "
                               "или jarvis_voice_note.",
            },
            "caption": {"type": "string", "description": "Необязательная подпись к файлу (для action=send_file)"},
        },
        "required": ["action"],
    },
}

JARVIS_TELEGRAM = {
    "name": "jarvis_telegram",
    "description": (
        "Личный аккаунт Telegram владельца (MTProto userbot — не бот, а полноценный вход как сам "
        "пользователь, см. docs/TELEGRAM.md) — читает диалоги, непрочитанные, текст и медиа сообщений, "
        "пишет и шлёт файлы/голосовые от имени владельца. Используется ТОЛЬКО по явной просьбе "
        "владельца и с его собственного аккаунта (не для рассылок незнакомым людям и не для чужих "
        "аккаунтов). status — настроен/авторизован ли; dialogs — список чатов (unread_only — только "
        "с непрочитанными); unread — сводка непрочитанных по всем чатам; read — прочитать последние "
        "сообщения конкретного чата (mark_read=true — также отметить прочитанным на всех устройствах, "
        "по умолчанию false — только посмотреть, не трогая счётчик); mark_read — отметить чат "
        "прочитанным без чтения; send — отправить текст; send_file — отправить файл/фото/голосовое "
        "(voice_note=true — как голосовое сообщение); download_media — скачать медиа конкретного "
        "сообщения на диск (message_id из read); react — поставить эмодзи-реакцию на сообщение "
        "(emoji='' снимает реакцию); edit_message — отредактировать СВОЁ ранее отправленное текстовое "
        "сообщение (чужие Telegram редактировать не даёт); delete_message — удалить сообщение "
        "(revoke=true по умолчанию — удаляет у всех участников чата); forward_message — переслать "
        "сообщение из from_chat в chat; set_typing — показать статус «печатает…» перед ответом "
        "(чисто косметика, не обязательна). Если authorized=false, объясни пользователю, что "
        "нужно один раз выполнить `jarvis telegram setup` в терминале — сам инструмент вход не запускает."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "dialogs", "unread", "read", "mark_read", "send", "send_file", "download_media",
                         "react", "edit_message", "delete_message", "forward_message", "set_typing"],
            },
            "chat": {
                "type": "string",
                "description": "Чат: 'me' (Избранное), @username, номер телефона контакта или числовой id "
                               "(из dialogs/unread) — для read/mark_read/send/send_file/download_media/react/"
                               "edit_message/delete_message/forward_message(куда)/set_typing.",
            },
            "limit": {"type": "integer", "description": "Сколько элементов вернуть (для dialogs/read), по умолчанию 20"},
            "unread_only": {"type": "boolean", "description": "Для dialogs — только чаты с непрочитанными; для read — только непрочитанные сообщения этого чата"},
            "mark_read": {"type": "boolean", "description": "Для read — также отметить чат прочитанным (по умолчанию false)"},
            "text": {"type": "string", "description": "Текст сообщения (для action=send/edit_message)"},
            "path": {"type": "string", "description": "Локальный путь к файлу/фото/голосовому (для action=send_file)"},
            "caption": {"type": "string", "description": "Подпись к файлу (для action=send_file)"},
            "voice_note": {"type": "boolean", "description": "Отправить файл как голосовое сообщение (для action=send_file)"},
            "message_id": {"type": "integer", "description": "ID сообщения (из read/dialogs) — для download_media/react/edit_message/delete_message/forward_message"},
            "emoji": {"type": "string", "description": "Эмодзи реакции, напр. '👍'/'❤'/'🔥' (для action=react; пусто — снять реакцию)"},
            "revoke": {"type": "boolean", "description": "Для delete_message — удалить у всех участников (true, по умолчанию) или только у себя (false)"},
            "from_chat": {"type": "string", "description": "Исходный чат, откуда пересылается сообщение (для action=forward_message)"},
            "seconds": {"type": "number", "description": "Сколько секунд показывать статус «печатает…» (для action=set_typing, по умолчанию 4, максимум 30)"},
        },
        "required": ["action"],
    },
}
