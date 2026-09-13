#!/usr/bin/env python3
"""
jarvis doctor — самодиагностика JARVIS одной командой, с автопочинкой.

    jarvis doctor            проверить всё и показать, что делать
    jarvis doctor --fix      то же + починить, что можно автоматически (ключ HUD, launchd, плагины, индекс хранилища…)
    jarvis doctor --json     машинно-читаемый отчёт (использует JARVIS.app)

Проверки (каждая — независима, падение одной не мешает другим):
  1. hermes установлен и отвечает                    7. launchd/Scheduled Tasks/systemd загружены
  2. модель настроена и РЕАЛЬНО отвечает (ping)     8. telethon импортируется тем же Python, что HUD
  3. плагины JARVIS включены и импортируются        9. права macOS (краткая выжимка selftest)
  4. API-сервер Hermes (.env) включён, ключ есть    10. хранилище ~/JARVIS и индекс
  5. gateway/API :8642 живой                        11. версия JARVIS и доступные обновления
  6. HUD отвечает на :8765 и знает ключ API

Идея: новичок при любой проблеме запускает `jarvis doctor --fix` и получает либо «всё зелёное», либо конкретный
следующий шаг человеческим языком. Без LLM (кроме одного короткого ping модели, который можно отключить --no-model).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# На Windows stdout/stderr при перенаправлении в файл/пайп (не TTY) используют системную
# кодировку консоли (обычно cp1252), а не UTF-8 — любой print() с кириллицей тогда падает
# с UnicodeEncodeError вместо того, чтобы просто напечататься. На Linux/macOS это не нужно
# (там локаль почти всегда UTF-8), поэтому ограничиваемся Windows.
if sys.platform == "win32":  # pragma: no cover — покрыто CI на windows-latest
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
JARVIS_HOME = HERMES_HOME / "jarvis"
HUD_PORT = int(os.environ.get("JARVIS_HUD_PORT", "8765"))
API_PORT = 8642
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
if IS_WINDOWS:
    PLUGINS = ("jarvis-core", "jarvis-windows", "jarvis-brain")
elif IS_LINUX:
    PLUGINS = ("jarvis-core", "jarvis-linux", "jarvis-brain")
else:
    PLUGINS = ("jarvis-core", "jarvis-macos", "jarvis-brain")
BIN = Path.home() / ".local" / "bin"

C = {"ok": "\033[1;32m✔\033[0m", "warn": "\033[1;33m⚠\033[0m", "fail": "\033[1;31m✖\033[0m", "fixed": "\033[1;36m⟳\033[0m", "skip": "\033[2m·\033[0m"}


class Check:
    def __init__(self, name: str):
        self.name, self.status, self.note, self.fix_hint, self.fixed = name, "ok", "", "", False

    def ok(self, note: str = ""):
        self.status, self.note = "ok", note
        return self

    def warn(self, note: str, fix: str = ""):
        self.status, self.note, self.fix_hint = "warn", note, fix
        return self

    def fail(self, note: str, fix: str = ""):
        self.status, self.note, self.fix_hint = "fail", note, fix
        return self

    def skip(self, note: str = ""):
        self.status, self.note = "skip", note
        return self

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "note": self.note, "fix": self.fix_hint, "fixed": self.fixed}


def sh(cmd: list[str], timeout: int = 20, env: dict | None = None) -> tuple[int, str]:
    try:
        if IS_WINDOWS:
            path = f"{BIN};" + os.environ.get("PATH", "")
        else:
            path = f"{BIN}:/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
        # На Windows консольные программы (schtasks.exe и т.п.) пишут в OEM-кодовой странице
        # консоли (GetOEMCP(), напр. cp866 на русской локали), а не в UTF-8 — см. тот же разбор
        # в scripts/setup_scheduled_tasks.py::_run(). encoding="utf-8" здесь не падает
        # (errors="replace" глотает несовпадения), но результат превращается в нечитаемую кашу,
        # из-за которой пользователь не может понять реальную причину ошибки в "jarvis doctor".
        enc = "oem" if IS_WINDOWS else "utf-8"
        p = subprocess.run(cmd, capture_output=True, text=True, encoding=enc, errors="replace", timeout=timeout,
                           env={**os.environ, "PATH": path, **(env or {})},
                           creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def http(url: str, timeout: float = 2.0, headers: dict | None = None) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(2000).decode(errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # любая сетевая ошибка = «не отвечает»
        return 0, str(e)[:100]


def read_env() -> dict:
    out = {}
    try:
        for line in (HERMES_HOME / ".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.split("#", 1)[0].strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def write_env(updates: dict) -> None:
    p = HERMES_HOME / ".env"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    for k, v in updates.items():
        lines = [ln for ln in lines if not ln.startswith(f"{k}=")]
        lines.append(f"{k}={v}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)


# ─────────────────────────────── проверки ───────────────────────────────

def check_hermes(fix: bool) -> Check:
    c = Check("Hermes Agent")
    hermes = shutil.which("hermes") or (str(BIN / "hermes") if (BIN / "hermes").exists() else None)
    if not hermes:
        return c.fail("команда hermes не найдена", "bash install.sh  (установит Hermes официальным скриптом)")
    code, out = sh([hermes, "--version"], timeout=30)
    if code != 0:
        return c.fail(f"hermes не запускается: {out.strip()[:120]}", "hermes doctor")
    return c.ok(out.strip().splitlines()[0][:60] if out.strip() else hermes)


def check_model(fix: bool, do_ping: bool) -> Check:
    c = Check("Модель LLM")
    code, out = sh(["hermes", "config", "get", "model"], timeout=30)
    model = out.strip().splitlines()[-1].strip() if code == 0 and out.strip() else ""
    # Некоторые версии/сборки `hermes config get` могут вывести текстовое сообщение об
    # отсутствующем значении (например, "not found"/"not set") вместо пустой строки — это НЕ
    # имя модели, и его нельзя показывать пользователю как будто модель настроена (см. тот же
    # разбор в scripts/model_switch.py::_clean_config_value(), тот же класс бага, что вызывал
    # "Модель ИИ: not found" на HUD).
    if model and any(m in model.lower() for m in ("not found", "not set", "нет значения", "не задано")):
        model = ""
    if not model or model in ("None", "null", ""):
        return c.fail("модель не настроена", "hermes model   (выберите OpenRouter/Anthropic/OpenAI/Ollama)")
    if not do_ping:
        return c.ok(f"{model} (ping пропущен)")
    t0 = time.time()
    code, out = sh(["hermes", "chat", "-q", "Ответь одним словом: ok"], timeout=90)
    dt = time.time() - t0
    text = out.strip()
    low = text.lower()
    # "attention required"/"cloudflare" ловит характерный блок Cloudflare (напр. у
    # inference-api.nousresearch.com при перегрузке/бане IP) — без этих слов такой ответ уже
    # покрывается "403"/"http 4", но явное совпадение даёт понятнее текст диагноза пользователю.
    # WinError 10061 / ConnectionRefused / "Connection error." — типичный признак того, что
    # model.provider=custom указывает на локальный OpenAI-совместимый сервер (LM Studio,
    # Ollama, свой прокси и т.п. на localhost:<порт>), который сейчас не запущен. Отличаем
    # этот случай от реальной проблемы с облачным провайдером (ключ/баланс/Cloudflare) —
    # подсказка тут другая: либо запустить локальный сервер, либо переключиться на облако.
    if any(k in low for k in ("connection error", "connectionrefused", "connection refused",
                                "10061", "winerror", "actively refused", "econnrefused")):
        return c.fail(f"{model} — локальный сервер не отвечает: {text[-160:] or 'нет ответа'}",
                      "проверьте, что локальный LLM-сервер (Ollama/LM Studio/свой) запущен на "
                      "указанном base_url; либо переключитесь на облако: hermes model")
    if code != 0 or not text or any(k in low for k in ("error code", "http 4", "http 5", "traceback",
                                                         "401", "403", "405", "429",
                                                         "attention required", "cloudflare", "permissiondeniederror")):
        return c.fail(f"{model} не отвечает: {text[-140:] or 'пустой ответ'}",
                      "hermes model → выберите рабочую модель; проверьте ключ провайдера и баланс")
    return c.ok(f"{model} отвечает ({dt:.1f} с)")


def check_plugins(fix: bool) -> Check:
    c = Check("Плагины JARVIS")
    missing_dirs = [p for p in PLUGINS if not (HERMES_HOME / "plugins" / p / "plugin.yaml").exists()]
    if missing_dirs:
        hint = "install.ps1 -Yes -NoScheduledTask" if IS_WINDOWS else "bash install.sh --yes --no-launchd --no-brew-tools --no-systemd-user"
        return c.fail(f"не установлены: {', '.join(missing_dirs)}", hint)
    code, out = sh(["hermes", "plugins", "list"], timeout=30)
    listed = [p for p in PLUGINS if p in out]
    if len(listed) < len(PLUGINS):
        if fix:
            sh(["hermes", "plugins", "enable", *PLUGINS], timeout=30)
            code, out = sh(["hermes", "plugins", "list"], timeout=30)
            if all(p in out for p in PLUGINS):
                c.fixed = True
                return c.ok("включены (исправлено)")
        return c.warn(f"не включены: {', '.join(p for p in PLUGINS if p not in listed)}",
                      "hermes plugins enable " + " ".join(PLUGINS))
    # импортируемость: синтаксис всех .py
    import py_compile
    bad = []
    for p in PLUGINS:
        for py in (HERMES_HOME / "plugins" / p).rglob("*.py"):
            try:
                py_compile.compile(str(py), doraise=True)
            except py_compile.PyCompileError as e:
                bad.append(f"{py.name}: {str(e)[:60]}")
    if bad:
        return c.fail("ошибки в коде плагинов: " + "; ".join(bad[:2]), "jarvis update --rollback  или  bash install.sh")
    return c.ok(f"{len(PLUGINS)}/3 включены, код компилируется")


def check_env_api(fix: bool) -> Check:
    c = Check("API-сервер Hermes (.env)")
    env = read_env()
    problems = {}
    if env.get("API_SERVER_ENABLED", "").lower() != "true":
        problems["API_SERVER_ENABLED"] = "true"
    if not env.get("API_SERVER_KEY"):
        import secrets
        problems["API_SERVER_KEY"] = secrets.token_hex(24)
    if not env.get("API_SERVER_HOST"):
        problems["API_SERVER_HOST"] = "127.0.0.1"
    if problems:
        if fix:
            write_env(problems)
            c.fixed = True
            return c.warn(f"добавлено в .env: {', '.join(problems)} — перезапустите: jarvis gateway restart && jarvis hud restart")
        return c.fail(f"в {HERMES_HOME}/.env нет: {', '.join(problems)}", "jarvis doctor --fix")
    return c.ok("API_SERVER_ENABLED=true, ключ задан")


def check_gateway(fix: bool) -> Check:
    c = Check(f"Gateway / API :{API_PORT}")
    st, _ = http(f"http://127.0.0.1:{API_PORT}/health")
    if st == 200:
        return c.ok("отвечает")
    if fix:
        sh(["jarvis", "gateway", "start"], timeout=30)
        for _ in range(10):
            time.sleep(1)
            if http(f"http://127.0.0.1:{API_PORT}/health")[0] == 200:
                c.fixed = True
                return c.ok("запущен (исправлено)")
    return c.fail("не отвечает — HUD-чат и мессенджеры не работают", "jarvis gateway start   (лог: hermes logs)")


def check_hud(fix: bool) -> Check:
    c = Check(f"HUD :{HUD_PORT}")
    st, body = http(f"http://127.0.0.1:{HUD_PORT}/api/status")
    if st != 200:
        if fix:
            sh(["jarvis", "hud", "start"], timeout=30)
            time.sleep(1.5)
            st, body = http(f"http://127.0.0.1:{HUD_PORT}/api/status")
            if st == 200:
                c.fixed = True
        if st != 200:
            return c.fail("не запущен", "jarvis hud   (лог: jarvis hud log)")
    try:
        j = json.loads(body)
    except ValueError:
        j = {}
    up = (j.get("hermes") or {}).get("up")
    # ключ HUD должен совпадать с .env — проверяем реальным запросом к API с ключом из .env
    key = read_env().get("API_SERVER_KEY", "")
    if key and up:
        st2, _ = http(f"http://127.0.0.1:{API_PORT}/v1/models", headers={"Authorization": f"Bearer {key}"})
        if st2 == 401:
            return c.fail("ключ в .env не совпадает с тем, что использует gateway", "jarvis gateway restart && jarvis hud restart")
    return c.ok("отвечает" + (", видит Hermes API" if up else "; Hermes API недоступен — см. пункт Gateway") + (" (исправлено)" if c.fixed else ""))


def check_launchd(fix: bool) -> Check:
    if IS_WINDOWS:
        c = Check("Автозапуск (Scheduled Tasks)")
        # Список задач держим в одном месте (setup_scheduled_tasks.TASKS), а не дублируем
        # литералом здесь — раньше список из 4 имён был продублирован вручную в этой функции,
        # и если кто-то добавлял/переименовывал задачу в setup_scheduled_tasks.py, doctor молча
        # продолжал сверяться со старым списком.
        try:
            sys.path.insert(0, str(JARVIS_HOME))
            from setup_scheduled_tasks import TASKS as ALL_TASKS
        except Exception:
            ALL_TASKS = ("JARVIS-HUD", "JARVIS-Gateway", "JARVIS-Updater", "JARVIS-App")
        code, out = sh(["schtasks", "/Query", "/FO", "LIST"], timeout=15)
        tasks = [t for t in ALL_TASKS if t in out]
        # Раньше самолечение срабатывало только при `if not tasks:` — то есть только когда
        # НИ ОДНОЙ задачи не было вовсе. Если из 4 задач зарегистрировалась только часть
        # (например, 1 из 4 — Gateway/HUD/App упали с "Access is denied" из-за старого бага
        # Count=999, см. _RESTART_ON_FAILURE, а Updater без RestartOnFailure прошёл), doctor
        # считал это успехом ("1 задач(и) в планировщике") и НЕ пытался чинить остальные —
        # отсюда и не поднимающиеся сами Gateway/HUD даже после `jarvis doctor --fix`.
        # Теперь сверяемся именно с полным набором.
        missing = [t for t in ALL_TASKS if t not in tasks]
        if missing:
            if fix:
                fix_code, fix_out = sh(
                    [sys.executable, str(JARVIS_HOME / "setup_scheduled_tasks.py"), "install",
                     "--home", str(HERMES_HOME), "--python", sys.executable], timeout=30)
                code, out = sh(["schtasks", "/Query", "/FO", "LIST"], timeout=15)
                tasks = [t for t in ALL_TASKS if t in out]
                missing = [t for t in ALL_TASKS if t not in tasks]
                if not missing:
                    c.fixed = True
                    return c.ok(f"{len(tasks)} из {len(ALL_TASKS)} задач(и) созданы (исправлено)")
                # setup_scheduled_tasks.py печатает по одной строке "✔/✖ <имя задачи>[: причина]"
                # на каждую задачу — вытаскиваем строки именно про недостающие задачи, чтобы
                # показать НАСТОЯЩУЮ причину отказа schtasks (а не только общий совет
                # переустановить), не заставляя пользователя копаться в отдельном логе.
                reasons = [ln.strip() for ln in fix_out.splitlines()
                           if ln.strip().startswith("✖") and any(t in ln for t in missing)]
                detail = ("; ".join(reasons) if reasons else
                          (fix_out.strip()[-300:] if fix_out.strip() else "install-скрипт не вывел причину"))
                if tasks:
                    return c.warn(
                        f"зарегистрировано только {len(tasks)} из {len(ALL_TASKS)} "
                        f"(не хватает: {', '.join(missing)}) — причина отказа: {detail}",
                        "schtasks /Query /TN " + missing[0] + " /V /FO LIST   (или переустановите: install.ps1 -Yes)")
            return c.warn("задачи не установлены — JARVIS не поднимется сам после входа в систему",
                          "install.ps1 -Yes  (шаг Scheduled Task)  или запускайте jarvis up вручную")
        return c.ok(f"{len(tasks)} из {len(ALL_TASKS)} задач(и) в планировщике")
    if IS_LINUX:
        c = Check("Автозапуск (systemd --user)")
        units = [u for u in ("jarvis-hud", "jarvis-gateway", "jarvis-updater") if
                 (Path.home() / ".config" / "systemd" / "user" / f"{u}.service").exists()]
        if not units:
            return c.warn("юниты не установлены — JARVIS не поднимется сам после входа в систему",
                          "bash install.sh --yes  (шаг systemd --user)  или запускайте jarvis up вручную")
        code, out = sh(["systemctl", "--user", "is-enabled", *units], timeout=10)
        enabled = [u for u, line in zip(units, out.splitlines(), strict=False) if line.strip() == "enabled"]
        missing = [u for u in units if u not in enabled]
        if missing and fix:
            sh(["systemctl", "--user", "enable", "--now", *missing], timeout=15)
            code, out = sh(["systemctl", "--user", "is-enabled", *missing], timeout=10)
            still_missing = [u for u, line in zip(missing, out.splitlines(), strict=False) if line.strip() != "enabled"]
            c.fixed = not still_missing
            missing = still_missing
        if missing:
            return c.warn(f"не включены: {', '.join(missing)}", "systemctl --user enable --now " + " ".join(missing))
        return c.ok(f"{len(units)} юнит(ов) включено" + (" (исправлено)" if c.fixed else ""))
    c = Check("Автозапуск (launchd)")
    if not IS_MAC:
        return c.skip("не macOS/Windows/Linux")
    la = Path.home() / "Library" / "LaunchAgents"
    plists = [p for p in ("ai.jarvis.hud", "ai.jarvis.gateway", "ai.jarvis.updater", "ai.jarvis.app") if (la / f"{p}.plist").exists()]
    if not plists:
        return c.warn("агенты не установлены — JARVIS не поднимется сам после перезагрузки", "bash install.sh --yes  (шаг launchd)  или запускайте jarvis up вручную")
    code, out = sh(["launchctl", "list"], timeout=10)
    loaded = [p for p in plists if p in out]
    missing = [p for p in plists if p not in loaded]
    if missing and fix:
        for p in missing:
            sh(["launchctl", "load", "-w", str(la / f"{p}.plist")], timeout=10)
        code, out = sh(["launchctl", "list"], timeout=10)
        missing = [p for p in plists if p not in out]
        c.fixed = not missing
    if missing:
        return c.warn(f"не загружены: {', '.join(missing)}", "launchctl load -w ~/Library/LaunchAgents/<имя>.plist")
    return c.ok(f"{len(loaded)} агент(ов) загружено" + (" (исправлено)" if c.fixed else ""))


def check_permissions(fix: bool) -> Check:
    c = Check("Права/окружение" if (IS_WINDOWS or IS_LINUX) else "Права macOS")
    selftest = JARVIS_HOME / "selftest.py"
    if not selftest.exists():
        return c.warn("selftest.py не установлен", "install.ps1" if IS_WINDOWS else "bash install.sh")
    code, out = sh([sys.executable, str(selftest), "--json"], timeout=180)
    try:
        rows = json.loads(out[out.index("["):]) if "[" in out else []
    except ValueError:
        return c.warn("selftest не вернул отчёт", "jarvis selftest")
    if not rows:
        return c.warn("selftest не вернул отчёт", "jarvis selftest")
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("results") or []
    perm = [r for r in rows if r.get("status") == "perm"]
    fail = [r for r in rows if r.get("status") == "fail"]
    if perm:
        note = "нет прав: " + ", ".join(sorted({r["note"].replace("нет прав: ", "") for r in perm}))
        if fix:
            sh([sys.executable, str(selftest), "--fix"], timeout=60)
            note += " — открыл нужные панели настроек"
        return c.warn(note, "jarvis selftest --fix  → выдайте права терминалу и python")
    if fail:
        return c.warn(f"{len(fail)} инструмент(ов) с ошибкой: " + ", ".join(r["tool"] for r in fail[:4]), "jarvis selftest")
    return c.ok(f"все {len(rows)} интеграции работают")


def check_vault(fix: bool) -> Check:
    c = Check("Хранилище ~/JARVIS")
    vault_py = HERMES_HOME / "plugins" / "jarvis-brain" / "vault.py"
    if not vault_py.exists():
        return c.warn("плагин jarvis-brain без vault (старая версия)", "jarvis update")
    code, out = sh([sys.executable, str(vault_py), "status", "--json"], timeout=60)
    try:
        st = json.loads(out)
    except ValueError:
        return c.warn(f"vault status не отвечает: {out.strip()[:80]}", "jarvis vault status")
    if not st.get("exists"):
        if fix:
            sh([sys.executable, str(vault_py), "init"], timeout=30)
            c.fixed = True
            return c.ok(f"создано {st['root']} (исправлено) — кладите туда файлы")
        return c.warn(f"папка {st['root']} ещё не создана", "jarvis vault open")
    extras = []
    if not st.get("pdf"):
        if IS_WINDOWS:
            extras.append("PDF не индексируются: winget install poppler")
        elif IS_LINUX:
            extras.append("PDF не индексируются: sudo apt install poppler-utils")
        else:
            extras.append("PDF не индексируются: brew install poppler")
    note = f"{st['files']} файлов, {len(st.get('sources', []))} проект(ов), скан {str(st.get('last_scan') or '—')[:16]}"
    if st["files"] == 0 and fix:
        sh([sys.executable, str(vault_py), "reindex"], timeout=300)
    return c.ok(note + (" · " + "; ".join(extras) if extras else ""))


def check_telegram(fix: bool) -> Check:
    """Проверить, что telethon реально импортируется ТЕМ ЖЕ интерпретатором Python, что
    запускает HUD/плагины (sys.executable — тот же venv, что install.ps1/install.sh кладут
    в PATH и передают в setup_scheduled_tasks.py/scheduled task).

    Раньше install.ps1 ставил telethon через `uv pip install` без явного --python: если
    что-то в окружении PowerShell-сессии уже выставляло $env:VIRTUAL_ENV/CONDA_PREFIX не на
    тот venv, пакет мог уйти в другой Python, чем тот, который реально использует HUD —
    install.ps1 печатал "✔ telethon установлен" (реальный успех pip), но HUD всё равно
    показывал "telethon не установлен", потому что `import telethon` в его собственном
    интерпретаторе падал. Эта проверка ловит именно такое расхождение: `hermes doctor` и HUD
    запускаются одним и тем же $VenvPy, так что если ЗДЕСЬ telethon не импортируется — значит
    не импортируется и у HUD, а не наоборот (ложной тревоги from HUD).
    """
    c = Check("Telegram (telethon)")
    code, out = sh([sys.executable, "-c", "import telethon; print(telethon.__version__)"], timeout=15)
    if code == 0 and out.strip():
        return c.ok(f"telethon {out.strip().splitlines()[-1]} — тот же интерпретатор, что у HUD")
    if fix:
        sh([sys.executable, "-m", "pip", "install", "-q", "telethon"], timeout=60)
        code, out = sh([sys.executable, "-c", "import telethon; print(telethon.__version__)"], timeout=15)
        if code == 0 and out.strip():
            c.fixed = True
            return c.ok(f"telethon {out.strip().splitlines()[-1]} (установлено сейчас)")
    return c.warn("не импортируется этим интерпретатором — Telegram userbot будет недоступен",
                  f'"{sys.executable}" -m pip install telethon   (jarvis telegram недоступен до этого)')


def check_version(fix: bool) -> Check:
    c = Check("Версия JARVIS")
    inst, upd = {}, {}
    try:
        inst = json.loads((JARVIS_HOME / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return c.warn("install.json не найден — установка неполная", "bash install.sh")
    try:
        upd = json.loads((JARVIS_HOME / "update.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    v = inst.get("version", "?")
    if upd.get("available"):
        return c.warn(f"{v} → доступно {upd.get('latest')}", "jarvis update")
    if upd.get("error"):
        return c.ok(f"{v} (последняя проверка обновлений не удалась: {upd['error'][:60]})")
    return c.ok(f"{v} · канал {inst.get('channel', 'stable')} · автообновление {inst.get('auto_update', 'check')}")


# ─────────────────────────────── отчёт ───────────────────────────────

def run(fix: bool, ping_model: bool, quick: bool) -> list[Check]:
    checks = [check_hermes(fix)]
    if checks[0].status == "fail":
        return checks
    checks.append(check_model(fix, do_ping=ping_model and not quick))
    checks.append(check_plugins(fix))
    checks.append(check_env_api(fix))
    checks.append(check_gateway(fix))
    checks.append(check_hud(fix))
    checks.append(check_launchd(fix))
    checks.append(check_telegram(fix))
    if not quick:
        checks.append(check_permissions(fix))
    checks.append(check_vault(fix))
    checks.append(check_version(fix))
    return checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="JARVIS doctor")
    ap.add_argument("--fix", action="store_true", help="чинить, что можно автоматически")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-model", action="store_true", help="не пинговать модель (быстрее, без расхода токенов)")
    ap.add_argument("--quick", action="store_true", help="без ping модели и selftest прав")
    args = ap.parse_args(argv)
    checks = run(args.fix, ping_model=not args.no_model, quick=args.quick)
    if args.json:
        print(json.dumps({"ok": all(c.status in ("ok", "skip") for c in checks), "checks": [c.as_dict() for c in checks]}, ensure_ascii=False, indent=1))
        return 0 if all(c.status != "fail" for c in checks) else 1
    print("\033[1;36mJ.A.R.V.I.S. doctor\033[0m" + ("  (режим --fix)" if args.fix else ""))
    width = max(len(c.name) for c in checks) + 2
    for c in checks:
        mark = C["fixed"] if c.fixed else C[c.status]
        print(f" {mark} {c.name:<{width}} {c.note}")
        if c.status in ("warn", "fail") and c.fix_hint:
            print(f"   {'':<{width}} → {c.fix_hint}")
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    if not fails and not warns:
        print("\n Всё в порядке, сэр.")
    elif fails:
        print(f"\n {len(fails)} проблем(ы). Начните с первой красной строки" + ("" if args.fix else " или запустите: jarvis doctor --fix"))
    else:
        print(f"\n Работает, но есть {len(warns)} замечание(я)." + ("" if args.fix else " jarvis doctor --fix попробует исправить."))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
