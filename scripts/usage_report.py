#!/usr/bin/env python3
"""
`jarvis usage` — локальный дашборд токенов/стоимости JARVIS, без сторонних сервисов.

Почему это нужно (аудит GitHub, 2026): десятки проектов вокруг агентов — TokenTelemetry,
tokscale, llm.log, TokenTracker, inferock-bench — сходятся на одном: разработчики хотят
видеть, сколько токенов/денег ушло, БЕЗ облачного аккаунта, прокси или переписывания кода
(см. docs/RESEARCH.md, Раунд 6). У нас эта задача даже проще: Hermes Agent уже пишет всё
нужное в $HERMES_HOME/state.db (таблицы `sessions`/`messages`, колонки input_tokens/
output_tokens/estimated_cost_usd — см. docs Hermes «Session Storage»). Раньше добраться до
этого можно было только вручную через `sqlite3`/`hermes usage`; теперь — одна команда
`jarvis usage`, которая эти данные читает (READ ONLY — файл не модифицируется) и показывает
разбивку по дням/моделям/платформам без внешних зависимостей (rich/pandas и т.п.).

Команды:
  jarvis usage                       — сводка за последние 30 дней (или --since)
  jarvis usage --by-model            — разбивка по модели
  jarvis usage --by-platform         — разбивка по платформе (cli/telegram/discord/cron/api…)
  jarvis usage --by-day              — разбивка по дням
  jarvis usage --since "7 days ago"  — период (тот же синтаксис, что и "7", "30", ISO-дата YYYY-MM-DD)
  jarvis usage --json                — машинно-читаемый вывод

Ничего не пишет и не блокирует Hermes: открывает state.db в режиме read-only URI
(`file:...?mode=ro`), поэтому безопасно запускать, даже пока Hermes работает.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

if sys.platform == "win32":  # pragma: no cover — покрыто CI на windows-latest
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

IS_WINDOWS = sys.platform == "win32"
_DEFAULT_HERMES_HOME = "~/.hermes"
HERMES_HOME = Path(os.environ.get("HERMES_HOME") or (os.environ.get("LOCALAPPDATA", "") + "/hermes" if IS_WINDOWS
                                                       else _DEFAULT_HERMES_HOME)).expanduser()
STATE_DB = HERMES_HOME / "state.db"


class UsageError(Exception):
    pass


def _parse_since(text: str) -> float:
    """"7", "7 days ago", "30 days", "2026-01-01" -> unix timestamp. По умолчанию — 30 дней назад."""
    text = (text or "").strip().lower()
    if not text:
        text = "30"
    # ISO-дата
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    # число дней, опционально с "days"/"days ago"/"дней"
    digits = "".join(c for c in text.split()[0] if c.isdigit()) if text.split() else ""
    days = int(digits) if digits else 30
    return (dt.datetime.now() - dt.timedelta(days=days)).timestamp()


def _connect() -> sqlite3.Connection:
    if not STATE_DB.exists():
        raise UsageError(f"{STATE_DB} не найден — похоже, Hermes ещё ни разу не запускался")
    # read-only URI: безопасно открывать, даже пока Hermes пишет в базу (WAL допускает параллельное чтение)
    uri = f"file:{STATE_DB.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.OperationalError as e:
        raise UsageError(f"не удалось открыть {STATE_DB}: {e}") from e
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def collect(since_ts: float) -> dict:
    """Возвращает сводные метрики. Устойчиво к разным версиям схемы Hermes (столбцы могли появиться позже)."""
    conn = _connect()
    try:
        cols = _columns(conn, "sessions")
        if not cols:
            raise UsageError("в state.db нет таблицы sessions — версия Hermes слишком старая или база повреждена")
        if "estimated_cost_usd" in cols and "actual_cost_usd" in cols:
            select_cost = "COALESCE(estimated_cost_usd, actual_cost_usd, 0.0)"
        elif "estimated_cost_usd" in cols:
            select_cost = "COALESCE(estimated_cost_usd, 0.0)"
        elif "actual_cost_usd" in cols:
            select_cost = "COALESCE(actual_cost_usd, 0.0)"
        else:
            select_cost = "0.0"
        select_model = "COALESCE(model, '(неизвестно)')" if "model" in cols else "'(неизвестно)'"
        select_source = "COALESCE(source, '(неизвестно)')" if "source" in cols else "'(неизвестно)'"
        select_in = "COALESCE(input_tokens, 0)" if "input_tokens" in cols else "0"
        select_out = "COALESCE(output_tokens, 0)" if "output_tokens" in cols else "0"
        rows = conn.execute(
            f"""SELECT id, started_at, {select_model} AS model, {select_source} AS source,
                       {select_in} AS input_tokens, {select_out} AS output_tokens, {select_cost} AS cost
                FROM sessions WHERE started_at >= ?""", (since_ts,)).fetchall()
    finally:
        conn.close()

    total = {"sessions": len(rows), "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    by_model: dict[str, dict] = {}
    by_source: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    for r in rows:
        tin, tout, cost = int(r["input_tokens"] or 0), int(r["output_tokens"] or 0), float(r["cost"] or 0.0)
        total["input_tokens"] += tin
        total["output_tokens"] += tout
        total["cost_usd"] += cost
        for bucket, key in ((by_model, r["model"]), (by_source, r["source"])):
            b = bucket.setdefault(key, {"sessions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            b["sessions"] += 1
            b["input_tokens"] += tin
            b["output_tokens"] += tout
            b["cost_usd"] += cost
        day = dt.datetime.fromtimestamp(r["started_at"]).strftime("%Y-%m-%d") if r["started_at"] else "?"
        b = by_day.setdefault(day, {"sessions": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        b["sessions"] += 1
        b["input_tokens"] += tin
        b["output_tokens"] += tout
        b["cost_usd"] += cost

    return {"total": total, "by_model": by_model, "by_source": by_source, "by_day": by_day}


def _fmt_usd(v: float) -> str:
    return f"${v:.4f}" if v else "$0.00 (локально/бесплатно?)"


def _print_table(title: str, rows: dict[str, dict], key_header: str) -> None:
    if not rows:
        return
    print(f"\n{title}")
    widths = [max(len(key_header), *(len(k) for k in rows)), 8, 12, 12, 10]
    header = f"{key_header:<{widths[0]}}  {'сессий':>{widths[1]}}  {'вход':>{widths[2]}}  {'выход':>{widths[3]}}  {'стоимость':>{widths[4]}}"
    print(header)
    print("-" * len(header))
    for key, v in sorted(rows.items(), key=lambda kv: kv[1]["cost_usd"], reverse=True):
        print(f"{key:<{widths[0]}}  {v['sessions']:>{widths[1]}}  {v['input_tokens']:>{widths[2]}}  "
              f"{v['output_tokens']:>{widths[3]}}  {_fmt_usd(v['cost_usd']):>{widths[4]}}")


def cmd_report(args: argparse.Namespace) -> int:
    try:
        data = collect(_parse_since(args.since))
    except UsageError as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    t = data["total"]
    print(f"JARVIS/Hermes — использование с {args.since or 'последних 30 дней'}")
    print(f"Сессий: {t['sessions']}  ·  Токенов: {t['input_tokens'] + t['output_tokens']:,} "
          f"(вход {t['input_tokens']:,} / выход {t['output_tokens']:,})  ·  Стоимость: {_fmt_usd(t['cost_usd'])}")
    if t["cost_usd"] == 0 and t["sessions"] > 0:
        print("  (0.00 — обычно значит: локальная модель через Ollama, или провайдер не публикует цены Hermes'у)")
    if args.by_model or args.all:
        _print_table("По модели", data["by_model"], "модель")
    if args.by_platform or args.all:
        _print_table("По платформе", data["by_source"], "платформа")
    if args.by_day or args.all:
        _print_table("По дням", data["by_day"], "день")
    if not (args.by_model or args.by_platform or args.by_day or args.all):
        print("\nПодробнее: jarvis usage --by-model | --by-platform | --by-day | --json")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jarvis usage", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="", help='например "7", "30", "2026-01-01" (по умолчанию 30 дней)')
    ap.add_argument("--by-model", action="store_true")
    ap.add_argument("--by-platform", action="store_true")
    ap.add_argument("--by-day", action="store_true")
    ap.add_argument("--all", action="store_true", help="показать все разбивки сразу")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
