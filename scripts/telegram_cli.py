#!/usr/bin/env python3
"""
`jarvis telegram` — CLI-обёртка над Telegram userbot (plugins/jarvis-core/telegram_userbot.py).

Работает вне процесса Hermes (в отличие от инструмента jarvis_telegram, который вызывает
модель), поэтому годится для разового интерактивного входа по номеру телефона из терминала:

  jarvis telegram setup                — задать api_id/api_hash (my.telegram.org) и войти по телефону+коду
  jarvis telegram status               — настроен ли, авторизован ли, под каким аккаунтом
  jarvis telegram unread               — сводка непрочитанных по всем чатам
  jarvis telegram dialogs [-unread]    — список чатов
  jarvis telegram logout               — выйти и забыть локальную сессию (отзывает и на стороне Telegram)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "jarvis-core"))
import telegram_userbot as tu

# На Windows stdout при перенаправлении использует системную кодировку консоли, а не UTF-8 —
# print() с кириллицей падает с UnicodeEncodeError вместо того, чтобы просто напечататься.
if sys.platform == "win32":  # pragma: no cover — покрыто CI на windows-latest
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def cmd_setup(args: argparse.Namespace) -> int:
    if not tu.is_available():
        print("✖ Модуль telethon не установлен. Выполните: pip install telethon", file=sys.stderr)
        return 1
    print(
        "Настройка личного аккаунта Telegram для JARVIS (MTProto, вход как вы сами — не бот).\n\n"
        "1. Откройте https://my.telegram.org и войдите под своим номером телефона\n"
        "2. «API development tools» → заполните любое название приложения (короткое имя тоже любое)\n"
        "3. Скопируйте api_id (число) и api_hash сюда.\n"
        "Подробности: docs/TELEGRAM.md\n"
    )
    if not tu.has_credentials() or args.api_id:
        api_id = args.api_id or input("api_id: ").strip()
        api_hash = args.api_hash or input("api_hash: ").strip()
        try:
            tu.set_credentials(api_id, api_hash)
        except tu.TelegramError as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
    if tu.is_authorized():
        print("✔ Уже авторизовано. Проверьте: jarvis telegram status")
        return 0

    phone = args.phone or input("Номер телефона (с кодом страны, например +79991234567): ").strip()
    try:
        sent = tu.send_code(phone)
    except tu.TelegramError as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    print("Код отправлен в Telegram (приложение или SMS).")
    code = input("Код из Telegram: ").strip()
    result = tu.sign_in(phone, code, sent["phone_code_hash"])
    if result.get("needs_password"):
        password = input("Облачный пароль Telegram (2FA): ").strip()
        result = tu.sign_in(phone, code, sent["phone_code_hash"], password=password)
    if not result.get("success"):
        print(f"✖ {result.get('error', 'не удалось войти')}", file=sys.stderr)
        return 1
    who = result.get("username") or result.get("phone") or str(result.get("user_id"))
    print(f"✔ Авторизовано как {who}. Проверьте: jarvis telegram status")
    return 0


def cmd_logout(_: argparse.Namespace) -> int:
    result = tu.logout()
    print("✔ Вышли из аккаунта, локальная сессия удалена." if result.get("success")
          else f"✖ {result.get('error', 'ошибка выхода')}")
    return 0 if result.get("success") else 1


def cmd_status(args: argparse.Namespace) -> int:
    st = tu.status()
    if args.json:
        print(json.dumps(st, ensure_ascii=False))
        return 0
    if not st.get("available"):
        print(f"✖ {st.get('error', 'telethon не установлен')}")
        return 1
    if not st.get("configured"):
        print("Telegram userbot не настроен. Выполните: jarvis telegram setup")
        return 1
    if not st.get("authorized"):
        print(f"api_id/api_hash заданы, но не авторизовано{': ' + st['error'] if st.get('error') else ''}. "
              f"Выполните: jarvis telegram setup")
        return 1
    who = st.get("username") or st.get("phone") or st.get("first_name") or "?"
    print(f"✔ Авторизовано как {who}")
    return 0


def cmd_unread(args: argparse.Namespace) -> int:
    result = tu.unread_summary()
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if not result.get("success"):
        print(f"✖ {result.get('error')}", file=sys.stderr)
        return 1
    print(f"Всего непрочитанных: {result['total_unread']} в {result['chats_with_unread']} чатах")
    for c in result["chats"]:
        print(f"  {c['name']}: {c['unread_count']}" + (f" (упоминаний: {c['unread_mentions']})" if c["unread_mentions"] else ""))
    return 0


def cmd_dialogs(args: argparse.Namespace) -> int:
    result = tu.list_dialogs(limit=args.limit, unread_only=args.unread)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if not result.get("success"):
        print(f"✖ {result.get('error')}", file=sys.stderr)
        return 1
    for d in result["dialogs"]:
        mark = f" [{d['unread_count']} непрочит.]" if d["unread_count"] else ""
        print(f"  {d['name']}{mark}  —  {d['last_message'][:60]}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="jarvis telegram", description=__doc__)
    p.add_argument("--json", action="store_true", help="машиночитаемый вывод, где применимо")
    sub = p.add_subparsers(dest="action", required=True)

    sp = sub.add_parser("setup", help="настроить api_id/api_hash и войти по телефону+коду")
    sp.add_argument("--api-id", default="")
    sp.add_argument("--api-hash", default="")
    sp.add_argument("--phone", default="")
    sp.set_defaults(func=cmd_setup)

    sp = sub.add_parser("logout", help="выйти и забыть локальную сессию")
    sp.set_defaults(func=cmd_logout)

    sp = sub.add_parser("status", help="настроен/авторизован ли Telegram userbot")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("unread", help="сводка непрочитанных по всем чатам")
    sp.set_defaults(func=cmd_unread)

    sp = sub.add_parser("dialogs", help="список чатов")
    sp.add_argument("-unread", "--unread-only", dest="unread", action="store_true")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_dialogs)

    ns = p.parse_args()
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
