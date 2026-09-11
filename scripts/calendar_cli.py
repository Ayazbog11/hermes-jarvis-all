#!/usr/bin/env python3
"""
`jarvis calendar` — CLI-обёртка над Google Calendar (plugins/jarvis-core/gcalendar.py).

Работает вне процесса Hermes (в отличие от инструмента jarvis_calendar, который
вызывает модель), поэтому годится для разового ввода OAuth-логина из терминала:

  jarvis calendar setup                — задать client_id (+необязательный secret) и войти через браузер
  jarvis calendar status               — настроен ли, авторизован ли, под каким email
  jarvis calendar today | tomorrow     — список событий
  jarvis calendar logout               — забыть локальную авторизацию (не отзывает доступ у Google)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "jarvis-core"))
import gcalendar

# На Windows stdout при перенаправлении использует системную кодировку консоли, а не UTF-8 —
# print() с кириллицей падает с UnicodeEncodeError вместо того, чтобы просто напечататься.
if sys.platform == "win32":  # pragma: no cover — покрыто CI на windows-latest
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def cmd_setup(args: argparse.Namespace) -> int:
    print(
        "Настройка Google Calendar для JARVIS.\n\n"
        "1. Откройте https://console.cloud.google.com/apis/credentials\n"
        "2. Создайте проект (если ещё нет) → «Create Credentials» → «OAuth client ID»\n"
        "3. Тип приложения: Desktop app\n"
        "4. Включите Google Calendar API: https://console.cloud.google.com/apis/library/calendar-json.googleapis.com\n"
        "5. Скопируйте Client ID (и, если показан, Client secret) сюда.\n"
        "Подробности со скриншотами: docs/CALENDAR.md\n"
    )
    client_id = args.client_id or input("Client ID: ").strip()
    client_secret = args.client_secret or input("Client secret (Enter, если не выдан): ").strip()
    try:
        gcalendar.set_client(client_id, client_secret)
    except gcalendar.GCalError as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    print("Client сохранён. Открываю браузер для входа в Google-аккаунт…")
    try:
        email = gcalendar.authorize(open_browser=not args.no_browser)
    except gcalendar.GCalError as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    print(f"✔ Авторизовано{f' как {email}' if email else ''}. Проверьте: jarvis calendar today")
    return 0


def cmd_logout(_: argparse.Namespace) -> int:
    gcalendar.revoke()
    print("✔ Локальная авторизация забыта (доступ на стороне Google не отозван — "
          "сделайте это на https://myaccount.google.com/permissions при желании).")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    st = gcalendar.status()
    if args_json:
        print(json.dumps(st, ensure_ascii=False))
        return 0
    if not st.get("configured"):
        print("Google Calendar не настроен. Выполните: jarvis calendar setup")
        return 1
    if not st.get("authorized"):
        print(f"Client настроен, но не авторизован{': ' + st['error'] if st.get('error') else ''}. Выполните: jarvis calendar setup")
        return 1
    print(f"✔ Авторизовано как {st.get('email', '?')}")
    return 0


def _print_events(date: dt.date, events: list[dict]) -> None:
    print(f"{date.isoformat()}:")
    if not events:
        print("  (событий нет)")
        return
    for e in events:
        loc = f" — {e['location']}" if e.get("location") else ""
        print(f"  {e['start_label']}–{e['end_label']}  {e['title']}{loc}  [{e['id']}]")


def cmd_day(args: argparse.Namespace) -> int:
    if not gcalendar.has_client() or not gcalendar.is_authorized():
        print("Не настроено. Выполните: jarvis calendar setup", file=sys.stderr)
        return 1
    today = dt.date.today()
    d = today if args.which == "today" else today + dt.timedelta(days=1)
    tz = dt.datetime.now().astimezone().strftime("%z")
    tz = f"{tz[:3]}:{tz[3:]}" if tz else "+00:00"
    time_min = f"{d.isoformat()}T00:00:00{tz}"
    time_max = f"{(d + dt.timedelta(days=1)).isoformat()}T00:00:00{tz}"
    try:
        events = gcalendar.list_events(time_min, time_max)
    except gcalendar.GCalError as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    _print_events(d, events)
    return 0


def main() -> int:
    global args_json
    p = argparse.ArgumentParser(prog="jarvis calendar", description=__doc__)
    p.add_argument("--json", action="store_true", help="машиночитаемый вывод, где применимо")
    sub = p.add_subparsers(dest="action", required=True)

    sp = sub.add_parser("setup", help="настроить client id и авторизоваться через браузер")
    sp.add_argument("--client-id", default="")
    sp.add_argument("--client-secret", default="")
    sp.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически, только напечатать ссылку")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("logout", help="забыть локальную авторизацию")
    sp.set_defaults(func=cmd_logout)

    sp = sub.add_parser("status", help="настроен/авторизован ли календарь")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("today", help="события на сегодня")
    sp.set_defaults(func=cmd_day, which="today")

    sp = sub.add_parser("tomorrow", help="события на завтра")
    sp.set_defaults(func=cmd_day, which="tomorrow")

    ns = p.parse_args()
    args_json = ns.json
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
