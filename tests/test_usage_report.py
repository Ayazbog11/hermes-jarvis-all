"""Тесты scripts/usage_report.py — против настоящих (временных) SQLite баз, без сети."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import time

import pytest


def load():
    spec = importlib.util.spec_from_file_location("jarvis_usage_report", "scripts/usage_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _make_state_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE sessions (
        id TEXT PRIMARY KEY, source TEXT, model TEXT, started_at REAL,
        input_tokens INTEGER, output_tokens INTEGER, estimated_cost_usd REAL, actual_cost_usd REAL)""")
    conn.executemany(
        "INSERT INTO sessions(id, source, model, started_at, input_tokens, output_tokens, estimated_cost_usd) "
        "VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


@pytest.fixture()
def m(monkeypatch, tmp_path):
    mod = load()
    monkeypatch.setattr(mod, "HERMES_HOME", tmp_path)
    monkeypatch.setattr(mod, "STATE_DB", tmp_path / "state.db")
    return mod


def test_missing_state_db_raises_usage_error(m):
    with pytest.raises(m.UsageError, match="не найден"):
        m.collect(0.0)


def test_collect_aggregates_by_model_source_day(m, tmp_path):
    now = time.time()
    _make_state_db(tmp_path / "state.db", [
        ("s1", "cli", "anthropic/claude-sonnet-4.6", now - 100, 5000, 1000, 0.04),
        ("s2", "telegram", "anthropic/claude-sonnet-4.6", now - 200, 3000, 500, 0.02),
        ("s3", "cron", "ollama/qwen3:8b", now - 300, 8000, 2000, 0.0),
    ])
    data = m.collect(now - 86400)
    assert data["total"]["sessions"] == 3
    assert data["total"]["input_tokens"] == 16000
    assert data["total"]["output_tokens"] == 3500
    assert data["total"]["cost_usd"] == pytest.approx(0.06)
    assert data["by_model"]["anthropic/claude-sonnet-4.6"]["sessions"] == 2
    assert data["by_model"]["ollama/qwen3:8b"]["cost_usd"] == 0.0
    assert data["by_source"]["cli"]["sessions"] == 1
    assert data["by_source"]["telegram"]["input_tokens"] == 3000


def test_collect_respects_since_cutoff(m, tmp_path):
    now = time.time()
    _make_state_db(tmp_path / "state.db", [
        ("old", "cli", "m1", now - 100 * 86400, 1000, 100, 0.01),
        ("new", "cli", "m1", now - 1, 2000, 200, 0.02),
    ])
    data = m.collect(now - 7 * 86400)
    assert data["total"]["sessions"] == 1
    assert data["total"]["input_tokens"] == 2000


def test_collect_tolerates_old_schema_without_cost_columns(m, tmp_path):
    conn = sqlite3.connect(tmp_path / "state.db")
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at REAL)")
    conn.execute("INSERT INTO sessions VALUES ('s1', ?)", (time.time(),))
    conn.commit()
    conn.close()
    data = m.collect(0.0)
    assert data["total"]["sessions"] == 1
    assert data["total"]["cost_usd"] == 0.0
    assert data["by_model"]["(неизвестно)"]["sessions"] == 1


def test_collect_missing_sessions_table_raises(m, tmp_path):
    conn = sqlite3.connect(tmp_path / "state.db")
    conn.execute("CREATE TABLE something_else (x INTEGER)")
    conn.commit()
    conn.close()
    with pytest.raises(m.UsageError, match="sessions"):
        m.collect(0.0)


@pytest.mark.parametrize("text,expect_recent", [
    ("", True), ("30", True), ("7", True), ("2020-01-01", False),
])
def test_parse_since_variants(m, text, expect_recent):
    ts = m._parse_since(text)
    now = time.time()
    if expect_recent:
        assert now - ts < 31 * 86400 + 5
    else:
        assert now - ts > 300 * 86400


def test_cmd_report_json_output(m, tmp_path, capsys):
    _make_state_db(tmp_path / "state.db", [("s1", "cli", "m1", time.time(), 100, 50, 0.001)])
    rc = m.main(["--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["total"]["sessions"] == 1


def test_cmd_report_missing_db_prints_error_and_exits_nonzero(m, capsys):
    rc = m.main([])
    assert rc == 1
    assert "не найден" in capsys.readouterr().err


def test_cmd_report_text_output_all_breakdowns(m, tmp_path, capsys):
    _make_state_db(tmp_path / "state.db", [
        ("s1", "cli", "m1", time.time(), 100, 50, 0.001),
        ("s2", "telegram", "m2", time.time(), 200, 100, 0.002),
    ])
    rc = m.main(["--all"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "По модели" in out and "По платформе" in out and "По дням" in out
