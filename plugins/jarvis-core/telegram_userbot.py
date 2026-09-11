"""
Telegram userbot — полноценный доступ JARVIS к личному аккаунту Telegram владельца
через MTProto (тот же протокол, что использует официальный клиент и tdlib), а не Bot API.

Почему это отдельный модуль от messenger.py/`hermes send`:
`hermes send` (см. messenger.py) умеет только ОТПРАВЛЯТЬ через Bot API токен бота — этого
достаточно для «пришли мне уведомление», но Bot API принципиально не даёт: читать историю
личных чатов пользователя, видеть непрочитанные, скачивать медиа из чужих сообщений, писать
от имени самого пользователя (не от бота) в чаты, где бот не состоит. Это ровно то, что умеет
tdlib-userbot в alex2772/kuni (см. docs/RESEARCH.md, Round 7) — вход по номеру телефона как
обычное приложение Telegram.

Раунд 7 сначала не портировал эту возможность, сочтя userbot-паттерн общим ToS-риском
(автоматизация личного аккаунта под видом человека часто используется для спама/накрутки —
именно это запрещают Telegram ToS и Terms of Service большинства платформ). Владелец этого
форка явно уточнил задачу: это ЕГО собственный аккаунт, он даёт согласие сам себе на то, чтобы
ассистент читал/писал от его имени, речь не идёт о массовой рассылке незнакомым людям или ботах
для накрутки — типичный личный ассистент («прочитай последние сообщения», «есть что-то
непрочитанное», «ответь другу вместо меня»), не отличается по сути от того, что делает
Telegram Desktop, когда открыт на компьютере. Поэтому здесь используется полноценный MTProto,
без урезаний по функциональности, но с явными локальными предохранителями:
  * все операции — только с сессией, которую пользователь сам создал через `jarvis telegram setup`
    (интерактивный вход: телефон → код из SMS/приложения → пароль 2FA, если включён);
  * сессия и api_id/api_hash хранятся только локально (chmod 600), никогда никуда не отправляются;
  * нет автоматического «слушателя» по умолчанию — чтение/отправка происходят только по явному
    вызову инструмента (или включённому пользователем триггеру), а не скрытым фоновым ботом.

Используется Telethon (`pip install telethon`) — чистый Python, реализует тот же протокол MTProto,
что и tdlib, без необходимости собирать C++ (tdlib требует cmake/openssl/зависимости, которые
плохо переносимы между macOS/Windows/Linux — то, от чего как раз страдает kuni на непривычных
платформах). Функционально — тот же уровень доступа: чтение сообщений/медиа, список диалогов
и непрочитанных, отправка текста/файлов/голосовых от имени владельца аккаунта.

Требуется api_id/api_hash — пользователь получает их один раз на https://my.telegram.org
(аналогично тому, как Google Calendar требует свой OAuth client, см. docs/CALENDAR.md) —
это официальный способ получить доступ к Telegram API для собственных приложений/скриптов.

Публичное API (все функции синхронные — Telethon сам управляет event loop через `telethon.sync`):
  has_credentials() -> bool
  set_credentials(api_id, api_hash) -> None
  is_authorized() -> bool
  status() -> dict
  send_code(phone) -> dict                         (шаг 1 входа)
  sign_in(phone, code, phone_code_hash, password=None) -> dict   (шаг 2 входа, 2FA при необходимости)
  logout() -> dict
  list_dialogs(limit=20, unread_only=False) -> dict
  unread_summary() -> dict
  read_messages(chat, limit=20, unread_only=False, mark_read=False) -> dict
  send_text(chat, text) -> dict
  send_file(chat, path, caption=None, voice_note=False) -> dict
  download_media(chat, message_id, out_dir=None) -> dict
  mark_read(chat) -> dict
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

try:
    from telethon.sync import TelegramClient
    from telethon.errors import (
        SessionPasswordNeededError,
        PhoneCodeInvalidError,
        PhoneCodeExpiredError,
        PhoneNumberInvalidError,
        FloodWaitError,
        RPCError,
    )
    _TELETHON_OK = True
except ImportError:  # telethon не установлен — модуль тихо отключается (как gcalendar без сети)
    TelegramClient = None  # type: ignore
    SessionPasswordNeededError = PhoneCodeInvalidError = PhoneCodeExpiredError = Exception  # type: ignore
    PhoneNumberInvalidError = FloodWaitError = RPCError = Exception  # type: ignore
    _TELETHON_OK = False


class TelegramError(Exception):
    """Человекочитаемая ошибка Telegram userbot (не бросается наружу инструментами)."""


def is_available() -> bool:
    """Установлен ли telethon в текущем окружении Python."""
    return _TELETHON_OK


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or "~/.hermes").expanduser()


def _data_dir() -> Path:
    base = os.environ.get("JARVIS_STATE_DIR")
    if not base:
        try:
            from plugins.plugin_storage import plugin_data_dir  # type: ignore

            base = str(plugin_data_dir("jarvis-core"))
        except Exception:
            base = str(_hermes_home() / "plugin-data" / "jarvis-core")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _restrict_permissions(path: Path) -> None:
    """Best-effort chmod 600 — см. gcalendar._restrict_permissions() для полного объяснения

    (на Windows POSIX-биты не действуют на NTFS-ACL, но безопасная попытка не вредит)."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _credentials_path() -> Path:
    return _data_dir() / "telegram_userbot_credentials.json"


def _session_path() -> Path:
    """Путь к файлу сессии Telethon (SQLite) — без расширения, Telethon сама добавит .session."""
    return _data_dir() / "telegram_userbot"


def has_credentials() -> bool:
    return _credentials_path().exists()


def set_credentials(api_id: int | str, api_hash: str) -> None:
    """Сохранить api_id/api_hash, полученные пользователем на https://my.telegram.org.

    Разовая настройка (см. docs/TELEGRAM.md), аналогично gcalendar.set_client().
    """
    try:
        api_id_int = int(str(api_id).strip())
    except ValueError as e:
        raise TelegramError("api_id должен быть числом (см. https://my.telegram.org)") from e
    api_hash = (api_hash or "").strip()
    if not api_hash:
        raise TelegramError("api_hash не может быть пустым")
    _credentials_path().write_text(
        json.dumps({"api_id": api_id_int, "api_hash": api_hash}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _restrict_permissions(_credentials_path())


def _load_credentials() -> dict:
    if not has_credentials():
        raise TelegramError(
            "Telegram userbot не настроен: нет api_id/api_hash. Выполните `jarvis telegram setup` "
            "(нужно один раз получить бесплатные api_id/api_hash на https://my.telegram.org — "
            "инструкция в docs/TELEGRAM.md)."
        )
    return json.loads(_credentials_path().read_text(encoding="utf-8"))


def is_authorized() -> bool:
    """Есть ли рабочая сессия (файл существует — окончательная проверка происходит при подключении)."""
    return _session_path().with_suffix(".session").exists()


def logout() -> dict:
    """Выйти из аккаунта и удалить локальную сессию (это отзывает сессию и на стороне Telegram —

    в отличие от gcalendar.revoke(), Telegram API поддерживает полноценный log_out())."""
    if not is_available():
        return {"success": False, "error": "telethon не установлен"}
    if not is_authorized():
        _forget_session()
        return {"success": True, "note": "локальной сессии и так не было"}
    try:
        creds = _load_credentials()
        with TelegramClient(str(_session_path()), creds["api_id"], creds["api_hash"]) as client:
            client.log_out()
    except Exception:
        pass  # даже если удалённый log_out не удался — всё равно чистим локально
    _forget_session()
    return {"success": True}


def _forget_session() -> None:
    for suffix in (".session", ".session-journal"):
        try:
            _session_path().with_suffix(suffix).unlink()
        except FileNotFoundError:
            pass


def status() -> dict:
    if not is_available():
        return {"available": False, "configured": False, "authorized": False,
                 "error": "telethon не установлен (pip install telethon)"}
    if not has_credentials():
        return {"available": True, "configured": False, "authorized": False}
    if not is_authorized():
        return {"available": True, "configured": True, "authorized": False}
    try:
        creds = _load_credentials()
        with TelegramClient(str(_session_path()), creds["api_id"], creds["api_hash"]) as client:
            me = client.get_me()
            return {
                "available": True, "configured": True, "authorized": True,
                "user_id": me.id, "username": me.username or "",
                "first_name": me.first_name or "", "phone": me.phone or "",
            }
    except Exception as e:
        return {"available": True, "configured": True, "authorized": False, "error": str(e)}


# ═══════════════════════════════ вход (шаг 1/2) ═════════════════════════════

def send_code(phone: str) -> dict:
    """Шаг 1 входа: запросить код у Telegram. Возвращает phone_code_hash, нужный для sign_in().

    Сессия остаётся открытой между send_code() и sign_in() внутри одного процесса CLI
    (см. scripts/telegram_cli.py cmd_setup) — Telethon требует того же соединения/сессии.
    """
    if not is_available():
        raise TelegramError("telethon не установлен (pip install telethon)")
    creds = _load_credentials()
    phone = (phone or "").strip()
    if not phone:
        raise TelegramError("Нужен номер телефона в международном формате, напр. +79991234567")
    client = TelegramClient(str(_session_path()), creds["api_id"], creds["api_hash"])
    client.connect()
    try:
        sent = client.send_code_request(phone)
        return {"success": True, "phone_code_hash": sent.phone_code_hash}
    except PhoneNumberInvalidError as e:
        raise TelegramError(f"Неверный номер телефона: {phone}") from e
    except FloodWaitError as e:
        raise TelegramError(f"Telegram просит подождать {e.seconds}с перед повторной попыткой") from e
    finally:
        client.disconnect()


def sign_in(phone: str, code: str, phone_code_hash: str, password: str | None = None) -> dict:
    """Шаг 2 входа: подтвердить код (и пароль 2FA, если включён). Сохраняет сессию на диск при успехе."""
    if not is_available():
        raise TelegramError("telethon не установлен (pip install telethon)")
    creds = _load_credentials()
    client = TelegramClient(str(_session_path()), creds["api_id"], creds["api_hash"])
    client.connect()
    try:
        try:
            me = client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                return {"success": False, "needs_password": True,
                         "error": "Включена двухфакторная аутентификация — нужен облачный пароль Telegram"}
            me = client.sign_in(password=password)
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
            raise TelegramError("Код неверный или устарел — запросите новый через `jarvis telegram setup`") from e
        _restrict_permissions(_session_path().with_suffix(".session"))
        return {"success": True, "user_id": me.id, "username": me.username or "", "phone": me.phone or ""}
    finally:
        client.disconnect()


# ═══════════════════════════════ клиент для операций ════════════════════════

class _Client:
    """Контекстный менеджер: открыть авторизованное MTProto-соединение на время одной операции.

    Явно не держим соединение открытым между вызовами инструмента (в отличие от постоянно
    работающего userbot-демона kuni) — каждый вызов инструмента короткоживущий, подключается,
    делает своё дело и отключается. Проще в отладке, не тратит соединение впустую между вызовами,
    не мешает параллельно открытому Telegram Desktop/телефону (Telegram допускает много активных
    сессий одновременно).
    """

    def __enter__(self) -> TelegramClient:
        if not is_available():
            raise TelegramError("telethon не установлен (pip install telethon)")
        if not has_credentials():
            raise TelegramError(
                "Telegram userbot не настроен. Выполните `jarvis telegram setup` в терминале."
            )
        if not is_authorized():
            raise TelegramError(
                "Telegram userbot не авторизован. Выполните `jarvis telegram setup` в терминале."
            )
        creds = _load_credentials()
        self._client = TelegramClient(str(_session_path()), creds["api_id"], creds["api_hash"])
        self._client.connect()
        if not self._client.is_user_authorized():
            self._client.disconnect()
            raise TelegramError(
                "Сессия недействительна (возможно, отозвана из настроек Telegram) — "
                "выполните `jarvis telegram setup` заново."
            )
        return self._client

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._client.disconnect()
        except Exception:
            pass


def _dialog_label(dialog) -> str:
    return dialog.name or dialog.title or str(dialog.id)


def _resolve_chat(client: TelegramClient, chat):
    """chat: username ('me', '@name'), телефон, числовой id или готовый peer — как в Telethon."""
    if isinstance(chat, str) and chat.strip().lstrip("-").isdigit():
        chat = int(chat.strip())
    return client.get_entity(chat)


# ═══════════════════════════════ операции ═══════════════════════════════════

def list_dialogs(limit: int = 20, unread_only: bool = False) -> dict:
    """Список диалогов (личные чаты, группы, каналы) — как открытая главная страница Telegram."""
    try:
        with _Client() as client:
            result = []
            for d in client.iter_dialogs(limit=limit * 3 if unread_only else limit):
                if unread_only and not d.unread_count:
                    continue
                result.append({
                    "id": d.id,
                    "name": _dialog_label(d),
                    "is_user": d.is_user,
                    "is_group": d.is_group,
                    "is_channel": d.is_channel,
                    "unread_count": d.unread_count,
                    "unread_mentions": d.unread_mentions_count,
                    "last_message": (d.message.text or d.message.raw_text or "") if d.message else "",
                    "last_message_date": d.date.isoformat() if d.date else "",
                })
                if len(result) >= limit:
                    break
            return {"success": True, "dialogs": result, "count": len(result)}
    except TelegramError as e:
        return {"success": False, "error": str(e)}
    except RPCError as e:
        return {"success": False, "error": f"Telegram API: {e}"}


def unread_summary() -> dict:
    """Сводка непрочитанных по всем диалогам — то, что видно в списке чатов бейджами."""
    try:
        with _Client() as client:
            chats = []
            total = 0
            for d in client.iter_dialogs():
                if d.unread_count:
                    total += d.unread_count
                    chats.append({
                        "id": d.id, "name": _dialog_label(d),
                        "unread_count": d.unread_count, "unread_mentions": d.unread_mentions_count,
                    })
            return {"success": True, "total_unread": total, "chats": chats, "chats_with_unread": len(chats)}
    except TelegramError as e:
        return {"success": False, "error": str(e)}
    except RPCError as e:
        return {"success": False, "error": f"Telegram API: {e}"}


def _message_dict(msg) -> dict:
    media_kind = ""
    if msg.photo:
        media_kind = "photo"
    elif msg.voice:
        media_kind = "voice"
    elif msg.video_note:
        media_kind = "video_note"
    elif msg.video:
        media_kind = "video"
    elif msg.audio:
        media_kind = "audio"
    elif msg.document:
        media_kind = "document"
    elif msg.sticker:
        media_kind = "sticker"
    return {
        "id": msg.id,
        "date": msg.date.isoformat() if msg.date else "",
        "out": bool(msg.out),
        "sender_id": msg.sender_id,
        "text": msg.text or msg.raw_text or "",
        "media": media_kind,
    }


def read_messages(chat, limit: int = 20, unread_only: bool = False, mark_read: bool = False) -> dict:
    """Прочитать текст/тип медиа последних сообщений чата. mark_read=True — также отметить прочитанным

    (иначе просмотр через инструмент не «съедает» реальный счётчик непрочитанных пользователя,
    что безопаснее по умолчанию — модель может заглянуть в чат, не трогая состояние на телефоне)."""
    try:
        with _Client() as client:
            entity = _resolve_chat(client, chat)
            fetch_limit = limit
            if unread_only:
                dialog = next((d for d in client.iter_dialogs() if d.id == client.get_peer_id(entity)), None)
                fetch_limit = dialog.unread_count if dialog and dialog.unread_count else 0
                if fetch_limit == 0:
                    return {"success": True, "messages": [], "count": 0, "note": "нет непрочитанных"}
            messages = [_message_dict(m) for m in client.iter_messages(entity, limit=fetch_limit)]
            if mark_read:
                client.send_read_acknowledge(entity)
            return {"success": True, "chat": _dialog_label_from_entity(client, entity),
                     "messages": messages, "count": len(messages)}
    except TelegramError as e:
        return {"success": False, "error": str(e)}
    except (ValueError, RPCError) as e:
        return {"success": False, "error": f"Не удалось найти чат/прочитать сообщения: {e}"}


def _dialog_label_from_entity(client: TelegramClient, entity) -> str:
    try:
        from telethon import utils as tl_utils
        return tl_utils.get_display_name(entity) or str(entity.id)
    except Exception:
        return str(getattr(entity, "id", ""))


def mark_read(chat) -> dict:
    try:
        with _Client() as client:
            entity = _resolve_chat(client, chat)
            client.send_read_acknowledge(entity)
            return {"success": True}
    except TelegramError as e:
        return {"success": False, "error": str(e)}
    except (ValueError, RPCError) as e:
        return {"success": False, "error": f"Не удалось найти чат: {e}"}


def send_text(chat, text: str) -> dict:
    """Отправить текстовое сообщение от имени владельца аккаунта (не от бота)."""
    text = (text or "").strip()
    if not text:
        return {"success": False, "error": "Пустой текст сообщения"}
    try:
        with _Client() as client:
            entity = _resolve_chat(client, chat)
            msg = client.send_message(entity, text)
            return {"success": True, "message_id": msg.id}
    except TelegramError as e:
        return {"success": False, "error": str(e)}
    except (ValueError, RPCError) as e:
        return {"success": False, "error": f"Не удалось отправить: {e}"}


def send_file(chat, path: str, caption: str | None = None, voice_note: bool = False) -> dict:
    """Отправить файл/фото/голосовое от имени владельца аккаунта."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"success": False, "error": f"Файл не найден: {path}"}
    try:
        with _Client() as client:
            entity = _resolve_chat(client, chat)
            msg = client.send_file(entity, str(p), caption=caption or "", voice_note=voice_note)
            return {"success": True, "message_id": getattr(msg, "id", None)}
    except TelegramError as e:
        return {"success": False, "error": str(e)}
    except (ValueError, RPCError) as e:
        return {"success": False, "error": f"Не удалось отправить файл: {e}"}


def download_media(chat, message_id: int, out_dir: str | None = None) -> dict:
    """Скачать медиа (фото/голосовое/документ/видео) конкретного сообщения на диск."""
    try:
        with _Client() as client:
            entity = _resolve_chat(client, chat)
            msgs = list(client.iter_messages(entity, ids=int(message_id)))
            msg = msgs[0] if msgs else None
            if not msg or not msg.media:
                return {"success": False, "error": "В этом сообщении нет медиа или оно не найдено"}
            target_dir = Path(out_dir).expanduser() if out_dir else _hermes_home() / "cache" / "jarvis" / "telegram"
            target_dir.mkdir(parents=True, exist_ok=True)
            saved = client.download_media(msg, file=str(target_dir) + os.sep)
            if not saved:
                return {"success": False, "error": "Не удалось скачать медиа"}
            return {"success": True, "path": str(saved)}
    except TelegramError as e:
        return {"success": False, "error": str(e)}
    except (ValueError, RPCError) as e:
        return {"success": False, "error": f"Не удалось скачать: {e}"}
