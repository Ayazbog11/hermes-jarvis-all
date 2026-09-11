"""
Google Calendar — кроссплатформенный календарь JARVIS (замена Outlook COM на Windows,
единая реализация вместо Calendar.app/khal per-OS).

Почему не Outlook / Windows.ApplicationModel.Appointments:
  * Outlook COM (был раньше) требует установленный и настроенный MS Outlook — многие
    пользователи Windows им не пользуются вовсе (Gmail/Google Workspace, встроенная
    почта и т.п.), так что «календарь» просто не работал у большинства.
  * Windows.ApplicationModel.Appointments (нативный календарь Windows/UWP) требует у
    вызывающего процесса package identity (MSIX-упаковку) — обычный .py/.ps1-скрипт без
    отдельной сборки и подписи получает `0x80073D54 The process has no package identity`
    и не может даже открыть store. Упаковка всего JARVIS в MSIX — отдельный большой
    проект, непропорциональный пользе одного инструмента.
  * Google Calendar работает из обычного unpackaged-процесса на любой ОС (Windows,
    macOS, Linux) одним и тем же кодом — только stdlib (urllib), без внешних
    зависимостей и без Google-специфичных SDK.

Поток авторизации: OAuth 2.0 "for iOS & Desktop Apps" (loopback redirect,
https://developers.google.com/identity/protocols/oauth2/native-app) — тот самый,
который Google рекомендует для macOS/Linux/Windows-приложений (в т.ч. без GUI):
локальный HTTP-сервер на 127.0.0.1 на случайном порту принимает редирект с кодом
авторизации после того, как пользователь один раз входит в свой Google-аккаунт в
обычном браузере. Токен (access + refresh) кэшируется в
$HERMES_HOME/plugin-data/jarvis-core/gcalendar_token.json; дальнейшие запросы работают
без браузера, обновляя access_token через refresh_token автоматически.

OAuth client id/secret: у Google для "Desktop app" client secret не является секретом
в криптографическом смысле (public client, PKCE обязателен) — тем не менее свой client
id пользователь должен создать сам в Google Cloud Console (это разовая пятиминутная
операция, описанная в docs/CALENDAR.md), т.к. Google requires проект для каждого
приложения и у автора этого репозитория нет возможности встраивать один общий client id
для всех инсталляций (внутренний OAuth consent screen, квоты, ToS).
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"


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


def _token_path() -> Path:
    return _data_dir() / "gcalendar_token.json"


def _client_path() -> Path:
    return _data_dir() / "gcalendar_client.json"


class GCalError(Exception):
    """Человекочитаемая ошибка Google Calendar (не бросается наружу инструментами)."""


# ═══════════════════════════════ client id/secret ═══════════════════════════

def has_client() -> bool:
    return _client_path().exists()


def set_client(client_id: str, client_secret: str = "") -> None:
    """Сохранить OAuth client id (и, опционально, client secret — Google выдаёт его для

    Desktop-типа клиента, но по спецификации не требует хранить его в секрете: это
    public client, вся защита — PKCE). Разовая настройка, см. docs/CALENDAR.md.
    """
    client_id = (client_id or "").strip()
    if not client_id:
        raise GCalError("client_id не может быть пустым")
    _client_path().write_text(
        json.dumps({"client_id": client_id, "client_secret": (client_secret or "").strip()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_client() -> dict:
    if not has_client():
        raise GCalError(
            "Google Calendar не настроен: нет client_id. Выполните `jarvis calendar setup` "
            "(нужно один раз создать бесплатный OAuth client в Google Cloud Console — "
            "инструкция в docs/CALENDAR.md)."
        )
    return json.loads(_client_path().read_text(encoding="utf-8"))


# ═══════════════════════════════ токены ═════════════════════════════════════

def is_authorized() -> bool:
    return _token_path().exists()


def _load_token() -> dict:
    try:
        return json.loads(_token_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_token(data: dict) -> None:
    tmp = _token_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_token_path())


def revoke() -> None:
    """Забыть авторизацию локально (не отзывает доступ на стороне Google — это делает

    сам пользователь на https://myaccount.google.com/permissions при желании)."""
    try:
        _token_path().unlink()
    except FileNotFoundError:
        pass


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Ловит один-единственный редирект http://127.0.0.1:<port>/ с ?code=...&state=...

    Полностью локально: код авторизации никогда не покидает машину пользователя,
    отправляется напрямую на TOKEN_ENDPOINT Google по HTTPS."""

    result: dict = {}  # заполняется классовым атрибутом — сервер живёт одну авторизацию

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.result["code"] = (qs.get("code") or [""])[0]
        _CallbackHandler.result["state"] = (qs.get("state") or [""])[0]
        _CallbackHandler.result["error"] = (qs.get("error") or [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = bool(_CallbackHandler.result["code"]) and not _CallbackHandler.result["error"]
        msg = "Готово, можно закрыть это окно." if ok else "Авторизация не удалась, можно закрыть это окно."
        self.wfile.write(f"<html><body style='font-family:sans-serif'><h2>JARVIS ⇄ Google Calendar</h2><p>{msg}</p></body></html>".encode())

    def log_message(self, format, *args):
        pass  # тишина в консоли — не спамим stdout установщика/CLI


def authorize(open_browser: bool = True, timeout: float = 180.0, print_fn=print) -> str:
    """Разовый вход через браузер (PKCE, loopback redirect). Возвращает email аккаунта.

    Блокирует вызывающий поток до завершения (или timeout секунд) — рассчитано на
    вызов из CLI (`jarvis calendar setup`), не из hook'ов агента.
    """
    client = _load_client()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    # порт 0 → ОС выдаёт свободный; фиксированный localhost-редирект недопустим,
    # т.к. порт может быть занят — Google разрешает произвольный порт на 127.0.0.1
    # для loopback-редиректов Desktop-приложений.
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = httpd.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/"
    _CallbackHandler.result = {}

    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)

    server_thread = threading.Thread(target=httpd.handle_request, daemon=True)
    server_thread.start()

    print_fn(f"Открываю браузер для входа в Google-аккаунт…\nЕсли не открылся сам — перейдите по ссылке:\n{url}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    server_thread.join(timeout=timeout)
    if server_thread.is_alive():
        httpd.server_close()
        raise GCalError(f"Не дождались авторизации за {int(timeout)}с — попробуйте снова.")

    result = _CallbackHandler.result
    if result.get("error"):
        raise GCalError(f"Google отклонил авторизацию: {result['error']}")
    if not result.get("code"):
        raise GCalError("Не получили код авторизации от Google (окно закрыто раньше времени?).")
    if result.get("state") != state:
        raise GCalError("Несовпадение state — авторизация отклонена из соображений безопасности, попробуйте снова.")

    token_req = {
        "client_id": client["client_id"],
        "client_secret": client.get("client_secret", ""),
        "code": result["code"],
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    tok = _post_form(TOKEN_ENDPOINT, token_req)
    tok["obtained_at"] = time.time()
    _save_token(tok)

    email = ""
    try:
        info = _get("https://www.googleapis.com/oauth2/v2/userinfo", tok["access_token"])
        email = info.get("email", "")
    except Exception:
        pass
    return email


def _post_form(url: str, fields: dict, timeout: float = 20.0) -> dict:
    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise GCalError(f"Google OAuth вернул ошибку {e.code}: {body[:300]}") from e
    except urllib.error.URLError as e:
        raise GCalError(f"Нет соединения с Google: {e.reason}") from e


def _access_token() -> str:
    tok = _load_token()
    if not tok:
        raise GCalError("Google Calendar не авторизован. Выполните `jarvis calendar setup`.")
    # обновляем заранее (за 2 минуты до истечения), чтобы не гонять лишний 401→refresh цикл
    expires_at = tok.get("obtained_at", 0) + tok.get("expires_in", 3600)
    if time.time() < expires_at - 120:
        return tok["access_token"]
    if not tok.get("refresh_token"):
        raise GCalError("Токен истёк и нет refresh_token — выполните `jarvis calendar setup` заново.")
    client = _load_client()
    new_tok = _post_form(TOKEN_ENDPOINT, {
        "client_id": client["client_id"],
        "client_secret": client.get("client_secret", ""),
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    })
    new_tok["refresh_token"] = tok["refresh_token"]  # Google не всегда возвращает его повторно
    new_tok["obtained_at"] = time.time()
    _save_token(new_tok)
    return new_tok["access_token"]


def _get(url: str, token: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise GCalError(f"Google Calendar API вернул {e.code}: {body[:300]}") from e
    except urllib.error.URLError as e:
        raise GCalError(f"Нет соединения с Google: {e.reason}") from e


def _api_call(method: str, path: str, params: dict | None = None, body: dict | None = None, timeout: float = 15.0) -> dict:
    token = _access_token()
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")
        raise GCalError(f"Google Calendar API вернул {e.code}: {body_txt[:300]}") from e
    except urllib.error.URLError as e:
        raise GCalError(f"Нет соединения с Google: {e.reason}") from e


# ═══════════════════════════════ высокоуровневые операции ══════════════════

def _fmt_time(iso: str, all_day: bool) -> str:
    if all_day:
        return "весь день"
    try:
        # 2026-09-11T10:00:00+03:00 → 10:00
        t = iso.split("T", 1)[1]
        return t[:5]
    except (IndexError, ValueError):
        return iso


def list_events(time_min_iso: str, time_max_iso: str, max_results: int = 20) -> list[dict]:
    """Список событий основного календаря в интервале [time_min_iso, time_max_iso)."""
    data = _api_call("GET", "/calendars/primary/events", params={
        "timeMin": time_min_iso,
        "timeMax": time_max_iso,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(max_results),
    })
    events = []
    for item in data.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})
        all_day = "date" in start
        events.append({
            "id": item.get("id"),
            "title": item.get("summary") or "(без названия)",
            "start": start.get("dateTime") or start.get("date", ""),
            "end": end.get("dateTime") or end.get("date", ""),
            "start_label": _fmt_time(start.get("dateTime") or start.get("date", ""), all_day),
            "end_label": _fmt_time(end.get("dateTime") or end.get("date", ""), all_day),
            "location": item.get("location", ""),
            "all_day": all_day,
        })
    return events


def create_event(title: str, start_iso: str, end_iso: str, timezone: str | None = None, description: str = "", location: str = "") -> dict:
    body = {
        "summary": title,
        "start": {"dateTime": start_iso, **({"timeZone": timezone} if timezone else {})},
        "end": {"dateTime": end_iso, **({"timeZone": timezone} if timezone else {})},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    item = _api_call("POST", "/calendars/primary/events", body=body)
    return {"id": item.get("id"), "title": item.get("summary"), "htmlLink": item.get("htmlLink", "")}


def delete_event(event_id: str) -> None:
    _api_call("DELETE", f"/calendars/primary/events/{urllib.parse.quote(event_id)}")


def status() -> dict:
    if not has_client():
        return {"configured": False, "authorized": False}
    if not is_authorized():
        return {"configured": True, "authorized": False}
    try:
        info = _get("https://www.googleapis.com/oauth2/v2/userinfo", _access_token())
        return {"configured": True, "authorized": True, "email": info.get("email", "")}
    except GCalError as e:
        return {"configured": True, "authorized": False, "error": str(e)}
