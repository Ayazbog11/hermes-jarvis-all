"""Тесты plugins/jarvis-core/telegram_userbot.py — без реального MTProto-соединения к Telegram

(TelegramClient полностью подменяется фейком; проверяем только логику модуля: хранение
credentials/сессии, обёртки над API, коды ошибок)."""

from __future__ import annotations

import json
import stat
import sys

import pytest

from conftest import load_plugin


@pytest.fixture
def tu():
    core = load_plugin("jarvis-core")
    return core.telegram_userbot


def test_is_available_true_in_test_env(tu):
    # telethon установлен в CI/тестовое окружение этого репозитория
    assert tu.is_available() is True


def test_status_not_configured(tu):
    assert tu.has_credentials() is False
    st = tu.status()
    assert st["available"] is True
    assert st["configured"] is False
    assert st["authorized"] is False


def test_set_credentials_persists(tu):
    tu.set_credentials("12345", "abcdef0123456789")
    assert tu.has_credentials() is True
    data = json.loads(tu._credentials_path().read_text(encoding="utf-8"))
    assert data["api_id"] == 12345
    assert data["api_hash"] == "abcdef0123456789"


def test_set_credentials_bad_api_id_raises(tu):
    with pytest.raises(tu.TelegramError):
        tu.set_credentials("not-a-number", "hash")


def test_set_credentials_empty_hash_raises(tu):
    with pytest.raises(tu.TelegramError):
        tu.set_credentials("123", "   ")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod bits don't apply to NTFS ACLs")
def test_set_credentials_restricts_file_permissions(tu):
    tu.set_credentials("123", "hash")
    mode = stat.S_IMODE(tu._credentials_path().stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_status_configured_not_authorized(tu):
    tu.set_credentials("123", "hash")
    st = tu.status()
    assert st == {"available": True, "configured": True, "authorized": False}


def test_is_authorized_false_without_session_file(tu):
    assert tu.is_authorized() is False


def test_logout_without_session_is_noop(tu):
    result = tu.logout()
    assert result["success"] is True


def test_send_code_without_credentials_raises(tu):
    with pytest.raises(tu.TelegramError):
        tu.send_code("+79991234567")


def test_client_context_manager_raises_when_not_configured(tu):
    with pytest.raises(tu.TelegramError):
        with tu._Client():
            pass


def test_client_context_manager_raises_when_not_authorized(tu):
    tu.set_credentials("123", "hash")
    with pytest.raises(tu.TelegramError):
        with tu._Client():
            pass


# ────────────────────── операции с полностью замоканным клиентом ───────────

class _FakeDialog:
    def __init__(self, id_, name, unread=0, mentions=0, text="", is_user=True):
        self.id = id_
        self.name = name
        self.title = name
        self.is_user = is_user
        self.is_group = False
        self.is_channel = False
        self.unread_count = unread
        self.unread_mentions_count = mentions
        self.date = None

        class _Msg:
            pass

        m = _Msg()
        m.text = text
        m.raw_text = text
        self.message = m if text else None


class _FakeMessage:
    def __init__(self, id_, text="", out=False, sender_id=1):
        self.id = id_
        self.date = None
        self.out = out
        self.sender_id = sender_id
        self.text = text
        self.raw_text = text
        self.photo = self.voice = self.video_note = self.video = None
        self.audio = self.document = self.sticker = None
        self.media = None


class _FakeClient:
    """Замена telethon.sync.TelegramClient — тот же публичный интерфейс, без сети."""

    calls: list = []

    def __init__(self, session, api_id, api_hash):
        _FakeClient.calls.append(("init", session, api_id, api_hash))
        self._authorized = True
        self.dialogs = [
            _FakeDialog(1, "Избранное", unread=0),
            _FakeDialog(2, "Друг", unread=3, text="привет"),
        ]
        self.messages = [_FakeMessage(100, text="старое"), _FakeMessage(101, text="новое")]
        self.messages[1].media = "photo"

    def connect(self):
        pass

    def disconnect(self):
        pass

    def is_user_authorized(self):
        return self._authorized

    def iter_dialogs(self, limit=None):
        return iter(self.dialogs[: limit] if limit else self.dialogs)

    def get_entity(self, chat):
        return chat

    def get_peer_id(self, entity):
        return entity if isinstance(entity, int) else 2

    def iter_messages(self, entity, limit=None, ids=None):
        if ids is not None:
            return iter([m for m in self.messages if m.id == ids])
        return iter(self.messages[: limit] if limit else self.messages)

    def send_read_acknowledge(self, entity):
        return True

    def send_message(self, entity, text):
        return _FakeMessage(999, text=text, out=True)

    def send_file(self, entity, path, caption="", voice_note=False):
        return _FakeMessage(998, out=True)

    def download_media(self, msg, file=None):
        return (file or "") + "downloaded.bin"

    def get_input_entity(self, entity):
        return entity

    def __call__(self, request):
        _FakeClient.calls.append(("request", request))
        if getattr(request, "reaction", None) and getattr(request.reaction[0], "emoticon", "") == "🚫invalid":
            raise ValueError("REACTION_INVALID")
        return True

    def edit_message(self, entity, message_id, text):
        if message_id == 999999:
            raise ValueError("MESSAGE_AUTHOR_REQUIRED")
        return _FakeMessage(message_id, text=text, out=True)

    def delete_messages(self, entity, message_ids, revoke=True):
        return [True]

    def forward_messages(self, entity, messages, from_peer):
        return [_FakeMessage(997, out=True)]

    def action(self, entity, act, auto_cancel=True):
        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Ctx()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def authorized(tu, monkeypatch, tmp_path):
    tu.set_credentials("123", "hash")
    session_file = tu._session_path().with_suffix(".session")
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text("fake")
    monkeypatch.setattr(tu, "TelegramClient", _FakeClient)
    _FakeClient.calls = []
    yield tu


def test_list_dialogs(authorized):
    result = authorized.list_dialogs(limit=10)
    assert result["success"] is True
    assert result["count"] == 2
    assert result["dialogs"][1]["unread_count"] == 3


def test_list_dialogs_unread_only(authorized):
    result = authorized.list_dialogs(limit=10, unread_only=True)
    assert result["success"] is True
    assert result["count"] == 1
    assert result["dialogs"][0]["name"] == "Друг"


def test_unread_summary(authorized):
    result = authorized.unread_summary()
    assert result["success"] is True
    assert result["total_unread"] == 3
    assert result["chats_with_unread"] == 1


def test_read_messages(authorized):
    result = authorized.read_messages(2, limit=5)
    assert result["success"] is True
    assert result["count"] == 2
    assert result["messages"][1]["text"] == "новое"


def test_mark_read(authorized):
    result = authorized.mark_read(2)
    assert result["success"] is True


def test_send_text(authorized):
    result = authorized.send_text(2, "привет!")
    assert result["success"] is True
    assert result["message_id"] == 999


def test_send_text_empty_fails(authorized):
    result = authorized.send_text(2, "   ")
    assert result["success"] is False


def test_send_file_missing_path(authorized):
    result = authorized.send_file(2, "/no/such/file.txt")
    assert result["success"] is False
    assert "не найден" in result["error"]


def test_send_file_success(authorized, tmp_path):
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"x")
    result = authorized.send_file(2, str(f), caption="подпись")
    assert result["success"] is True


def test_download_media(authorized, tmp_path):
    result = authorized.download_media(2, 101, out_dir=str(tmp_path))
    assert result["success"] is True
    assert "downloaded.bin" in result["path"]


def test_download_media_no_message_found(authorized):
    result = authorized.download_media(2, 12345)
    assert result["success"] is False


# ────────────────────── новые операции по образцу kuni (Round 12) ──────────

def test_react_adds_reaction(authorized):
    result = authorized.react(2, 101, "👍")
    assert result["success"] is True
    assert result["reacted"] == "👍"


def test_react_empty_emoji_clears_reaction(authorized):
    result = authorized.react(2, 101, "")
    assert result["success"] is True
    assert result["reacted"] is None


def test_react_invalid_reaction_reports_error_not_crash(authorized):
    result = authorized.react(2, 101, "🚫invalid")
    assert result["success"] is False
    assert "Telegram" in result["error"]


def test_edit_message_success(authorized):
    result = authorized.edit_message(2, 999, "исправленный текст")
    assert result["success"] is True


def test_edit_message_empty_text_fails(authorized):
    result = authorized.edit_message(2, 999, "   ")
    assert result["success"] is False


def test_edit_message_not_own_reports_error(authorized):
    result = authorized.edit_message(2, 999999, "текст")
    assert result["success"] is False


def test_delete_message_default_revokes(authorized):
    result = authorized.delete_message(2, 101)
    assert result["success"] is True
    assert result["revoked"] is True


def test_delete_message_no_revoke(authorized):
    result = authorized.delete_message(2, 101, revoke=False)
    assert result["success"] is True
    assert result["revoked"] is False


def test_forward_message_success(authorized):
    result = authorized.forward_message(2, 1, 101)
    assert result["success"] is True
    assert result["message_id"] == 997


def test_set_typing_success(authorized, monkeypatch):
    monkeypatch.setattr(authorized.time, "sleep", lambda s: None)  # не ждать реально в тесте
    result = authorized.set_typing(2, seconds=1)
    assert result["success"] is True


# ────────────────────────── tool_jarvis_telegram (обработчик) ──────────────

def test_tool_jarvis_telegram_status_not_configured(ctx):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "status"}))
    assert out["configured"] is False


def test_tool_jarvis_telegram_needs_setup(ctx):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "dialogs"}))
    assert out["success"] is False
    assert out["needs_setup"] is True


def test_tool_jarvis_telegram_send_requires_chat(ctx, authorized):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "send", "text": "hi"}))
    assert out["success"] is False
    assert "chat" in out["error"]


def test_tool_jarvis_telegram_unknown_action(ctx, authorized):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "bogus"}))
    assert out["success"] is False


def test_tool_jarvis_telegram_react(ctx, authorized):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "react", "chat": 2, "message_id": 101, "emoji": "🔥"}))
    assert out["success"] is True


def test_tool_jarvis_telegram_react_requires_message_id(ctx, authorized):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "react", "chat": 2, "emoji": "🔥"}))
    assert out["success"] is False


def test_tool_jarvis_telegram_edit_message(ctx, authorized):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "edit_message", "chat": 2, "message_id": 999, "text": "новый текст"}))
    assert out["success"] is True


def test_tool_jarvis_telegram_delete_message_default_revoke(ctx, authorized, monkeypatch):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "delete_message", "chat": 2, "message_id": 101}))
    assert out["success"] is True
    assert out["revoked"] is True


def test_tool_jarvis_telegram_forward_message(ctx, authorized):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "forward_message", "chat": 2, "from_chat": 1, "message_id": 101}))
    assert out["success"] is True


def test_tool_jarvis_telegram_forward_message_requires_from_chat(ctx, authorized):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "forward_message", "chat": 2, "message_id": 101}))
    assert out["success"] is False


def test_tool_jarvis_telegram_set_typing(ctx, authorized, monkeypatch):
    monkeypatch.setattr(authorized.time, "sleep", lambda s: None)
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_telegram({"action": "set_typing", "chat": 2}))
    assert out["success"] is True
