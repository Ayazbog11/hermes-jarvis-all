"""Google Calendar (gcalendar.py): состояние клиента/токена, PKCE, форматирование —

без реальных сетевых вызовов к Google (изолировано через JARVIS_STATE_DIR).
"""

from __future__ import annotations

import json
import stat
import sys

import pytest

from conftest import load_plugin


@pytest.fixture
def gcal():
    core = load_plugin("jarvis-core")
    return core.gcalendar


def test_status_not_configured(gcal):
    assert gcal.has_client() is False
    assert gcal.is_authorized() is False
    st = gcal.status()
    assert st == {"configured": False, "authorized": False}


def test_set_client_persists(gcal):
    gcal.set_client("123-abc.apps.googleusercontent.com", "shh")
    assert gcal.has_client() is True
    data = json.loads(gcal._client_path().read_text(encoding="utf-8"))
    assert data["client_id"] == "123-abc.apps.googleusercontent.com"
    assert data["client_secret"] == "shh"


def test_set_client_empty_id_raises(gcal):
    with pytest.raises(gcal.GCalError):
        gcal.set_client("   ")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod bits don't apply to NTFS ACLs")
def test_set_client_restricts_file_permissions(gcal):
    gcal.set_client("123-abc.apps.googleusercontent.com", "shh")
    mode = stat.S_IMODE(gcal._client_path().stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX chmod bits don't apply to NTFS ACLs")
def test_save_token_restricts_file_permissions(gcal):
    gcal._save_token({"access_token": "x", "expires_in": 3600, "obtained_at": 0})
    mode = stat.S_IMODE(gcal._token_path().stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_status_configured_not_authorized(gcal):
    gcal.set_client("client-id")
    st = gcal.status()
    assert st == {"configured": True, "authorized": False}


def test_pkce_pair_is_valid_and_random(gcal):
    v1, c1 = gcal._pkce_pair()
    v2, c2 = gcal._pkce_pair()
    assert v1 != v2 and c1 != c2
    assert len(v1) >= 43  # RFC 7636 minimum verifier length
    # challenge не должен содержать padding '=' (urlsafe_b64encode + rstrip)
    assert "=" not in c1 and "=" not in v1


def test_fmt_time_all_day_and_timed(gcal):
    assert gcal._fmt_time("2026-09-11", True) == "весь день"
    assert gcal._fmt_time("2026-09-11T14:30:00+03:00", False) == "14:30"


def test_access_token_without_authorization_raises(gcal):
    gcal.set_client("client-id")
    with pytest.raises(gcal.GCalError):
        gcal._access_token()


def test_revoke_removes_token_file(gcal, tmp_path):
    gcal._token_path().parent.mkdir(parents=True, exist_ok=True)
    gcal._save_token({"access_token": "x", "expires_in": 3600, "obtained_at": 0})
    assert gcal.is_authorized() is True
    gcal.revoke()
    assert gcal.is_authorized() is False
    gcal.revoke()  # второй раз — не должен бросать (FileNotFoundError проглатывается)


def test_load_client_missing_raises_helpful_error(gcal):
    with pytest.raises(gcal.GCalError, match="jarvis calendar setup"):
        gcal._load_client()


def test_tool_jarvis_calendar_status(ctx):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_calendar({"action": "status"}))
    assert out["success"] is True
    assert out["configured"] is False


def test_tool_jarvis_calendar_needs_setup_when_not_authorized(ctx):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    out = json.loads(core.tool_jarvis_calendar({"action": "today"}))
    assert out["success"] is False
    assert out["needs_setup"] is True
    assert "jarvis calendar setup" in out["error"]


def test_tool_jarvis_calendar_delete_without_id(ctx, monkeypatch):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    monkeypatch.setattr(core.gcalendar, "has_client", lambda: True)
    monkeypatch.setattr(core.gcalendar, "is_authorized", lambda: True)
    out = json.loads(core.tool_jarvis_calendar({"action": "delete"}))
    assert out["success"] is False and "event_id" in out["error"]


def test_tool_jarvis_calendar_unknown_action(ctx, monkeypatch):
    core = load_plugin("jarvis-core")
    core.register(ctx)
    monkeypatch.setattr(core.gcalendar, "has_client", lambda: True)
    monkeypatch.setattr(core.gcalendar, "is_authorized", lambda: True)
    out = json.loads(core.tool_jarvis_calendar({"action": "bogus"}))
    assert out["success"] is False
