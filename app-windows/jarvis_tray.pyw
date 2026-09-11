#!/usr/bin/env python3
"""
JARVIS — значок в системном трее Windows (аналог app/JarvisMenuBar.swift на macOS).

Что делает:
  • иконка в трее: цвет статуса (HUD/gateway работают/недоступны/идёт обновление);
  • меню правой/левой кнопкой: открыть HUD, голосовой чат, старт/стоп сервисов,
    база знаний, обновление, настройки, логи, диагностика;
  • раз в 5 минут — проверяет статус сервисов и update.json (его пишет update.py --auto,
    запускаемый Планировщиком заданий: см. scripts/setup_scheduled_tasks.py);
  • при доступном обновлении — пункт «Обновить до X» и toast-уведомление.
Всё «тяжёлое» делает bin/jarvis.ps1 — этот трей лишь удобная кнопка над ним.

Зависимости (ставятся install.ps1 в venv Hermes): pystray, pillow.
Запуск:  pythonw.exe app-windows/jarvis_tray.pyw   (pythonw — без консольного окна)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    sys.stderr.write(
        "Нужны пакеты pystray и pillow: pip install pystray pillow\n"
        "(install.ps1 ставит их автоматически в venv Hermes; запустите вручную для разработки)\n"
    )
    raise

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

IS_WINDOWS = sys.platform == "win32"

HERMES_HOME = Path(os.environ.get("HERMES_HOME") or
                    (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes")).expanduser()
JARVIS_HOME = HERMES_HOME / "jarvis"
JARVIS_BIN = HERMES_HOME / "bin" / "jarvis.ps1"
HUD_PORT = os.environ.get("JARVIS_HUD_PORT", "8765")
HUD_URL = f"http://127.0.0.1:{HUD_PORT}"
HERMES_API = "http://127.0.0.1:8642"
FIRST_RUN_MARKER = JARVIS_HOME / ".app-first-run-done"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def http_get(url: str, timeout: float = 2.0) -> tuple[bool, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            ok = r.status == 200
            data = json.loads(r.read().decode("utf-8") or "{}")
            return ok, data
    except Exception:
        return False, {}


def run_jarvis(args: list[str], timeout: int = 60) -> tuple[int, str]:
    """Запустить jarvis.ps1 <args> и вернуть (код, вывод) — синхронно, звать из фонового потока."""
    cmd = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(JARVIS_BIN), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def run_jarvis_async(args: list[str], on_done=None) -> None:
    def worker():
        code, out = run_jarvis(args)
        if on_done:
            on_done(code, out)
    threading.Thread(target=worker, daemon=True).start()


def open_terminal(command: str) -> None:
    """Открыть интерактивную команду в новом окне PowerShell (голосовой чат и т.п.)."""
    ps = f"$env:HERMES_HOME = '{HERMES_HOME}'; {command}"
    subprocess.Popen(["powershell.exe", "-NoLogo", "-NoExit", "-Command", ps],
                     creationflags=subprocess.CREATE_NEW_CONSOLE if IS_WINDOWS else 0)


def notify(title: str, body: str) -> None:
    if _icon is not None:
        try:
            _icon.notify(body, title)
            return
        except Exception:
            pass
    esc_t, esc_b = title.replace("'", "''"), body.replace("'", "''")
    subprocess.Popen(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
         "Add-Type -AssemblyName System.Windows.Forms; $n = New-Object System.Windows.Forms.NotifyIcon; "
         "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
         f"$n.ShowBalloonTip(5000, '{esc_t}', '{esc_b}', [System.Windows.Forms.ToolTipIcon]::Info); "
         "Start-Sleep -Seconds 5; $n.Dispose()"],
        creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
    )


def ask_text(title: str, prompt: str) -> str | None:
    """Простое модальное окно ввода текста — tkinter, стандартная библиотека, есть везде."""
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    value = simpledialog.askstring(title, prompt, parent=root)
    root.destroy()
    return value


def confirm(title: str, text: str, ok_label: str = "Да", cancel_label: str = "Отмена") -> bool:
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    result = messagebox.askyesno(title, text, parent=root)
    root.destroy()
    return bool(result)


def info_choice(title: str, text: str, buttons: list[str]) -> int:
    """Показать buttons[0]/buttons[1] как Yes/No; возвращает 0 для первой кнопки, 1 для второй."""
    return 0 if confirm(title, text, buttons[0], buttons[1] if len(buttons) > 1 else "Отмена") else 1


# ─────────────────────────────── мастер первого запуска ────────────────

def doctor_json() -> dict:
    code, out = run_jarvis(["doctor", "--json", "--quick"], timeout=90)
    if "{" in out:
        try:
            return json.loads(out[out.index("{"):])
        except ValueError:
            pass
    return {}


def first_run_wizard(force: bool = False) -> None:
    if not force and FIRST_RUN_MARKER.exists():
        return
    FIRST_RUN_MARKER.parent.mkdir(parents=True, exist_ok=True)
    FIRST_RUN_MARKER.write_text("1", encoding="utf-8")

    if info_choice("Добро пожаловать. Я JARVIS.",
                   "Я живу в системном трее — значок ◉ справа внизу, рядом с часами.\n\n"
                   "Сейчас за минуту проверим, что всё готово: модель, права Windows, папка для ваших файлов.",
                   ["Проверить", "Позже"]) != 0:
        return

    j = doctor_json()
    checks = j.get("checks", [])

    def status(name: str) -> tuple[str, str, str]:
        for c in checks:
            if str(c.get("name", "")).startswith(name):
                return c.get("status", "skip"), c.get("note", ""), c.get("fix", "")
        return "skip", "", ""

    model_st, model_note, _ = status("Модель")
    if model_st == "fail":
        if info_choice("Модель не настроена или не отвечает",
                       model_note + "\n\nБез модели JARVIS не может думать. Рекомендую OpenRouter "
                       "(один ключ — сотни моделей) или Ollama (локально, бесплатно).",
                       ["Открыть мастер модели", "Пропустить"]) == 0:
            open_terminal("hermes model; jarvis gateway restart")

    if info_choice("Права и настройка Windows",
                   "Чтобы читать календарь Outlook, показывать уведомления и делать скриншоты, "
                   "может понадобиться разрешить это в Параметрах Windows. Проверка займёт ~20 секунд.",
                   ["Проверить (selftest --fix)", "Позже"]) == 0:
        open_terminal("jarvis selftest --fix")

    _, vault_note, _ = status("Хранилище")
    choice = info_choice("Ваши файлы",
                         "Папка %USERPROFILE%\\JARVIS — моё хранилище: кладите туда документы, PDF, заметки, "
                         "целые проекты (`jarvis vault add <папка>`). Я читаю их содержимое и ищу по нему.\n\n"
                         + (("Сейчас: " + vault_note) if vault_note else ""),
                         ["Открыть папку и HUD", "Только HUD"])
    run_jarvis(["vault", "init"])
    if choice == 0:
        os.startfile(str(Path.home() / "JARVIS"))
    webbrowser.open(HUD_URL)
    api_ok = status("Gateway")[0] == "ok"
    if not api_ok:
        notify("JARVIS", "Сервисы поднимаются… если через минуту HUD пишет «нет связи» — меню → Диагностика.")


# ─────────────────────────────── иконка/статус ──────────────────────────

def make_icon_image(color: tuple[int, int, int, int]) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, size - 6, size - 6), fill=color)
    d.ellipse((22, 22, size - 22, size - 22), fill=(0, 0, 0, 0))
    return img


COLOR_OFF = (140, 140, 140, 255)
COLOR_UPDATING = (255, 149, 0, 255)
COLOR_PARTIAL = (255, 214, 10, 255)
COLOR_OK = (0, 200, 220, 255)


class State:
    def __init__(self):
        self.hud_up = False
        self.api_up = False
        self.version = "—"
        self.latest = ""
        self.update_available = False
        self.updating = False
        self.lock = threading.Lock()


_icon: pystray.Icon | None = None
_state = State()


def refresh(icon: pystray.Icon) -> None:
    inst = read_json(JARVIS_HOME / "install.json")
    upd = read_json(JARVIS_HOME / "update.json")
    with _state.lock:
        _state.version = inst.get("version", "—")
        _state.update_available = bool(upd.get("available"))
        _state.latest = upd.get("latest", "")

    ok, j = http_get(f"{HUD_URL}/api/status")
    hud_up = ok
    api_up = bool((j.get("hermes") or {}).get("up")) if ok else False
    if not ok:
        api_ok, _ = http_get(f"{HERMES_API}/health")
        api_up = api_ok
    with _state.lock:
        _state.hud_up = hud_up
        _state.api_up = api_up
    paint(icon)


def paint(icon: pystray.Icon) -> None:
    with _state.lock:
        if _state.updating:
            color = COLOR_UPDATING
        elif _state.hud_up and _state.api_up:
            color = COLOR_OK
        elif _state.hud_up or _state.api_up:
            color = COLOR_PARTIAL
        else:
            color = COLOR_OFF
        tip = (f"JARVIS {_state.version} · HUD {'on' if _state.hud_up else 'off'} · "
               f"API {'on' if _state.api_up else 'off'}")
        if _state.update_available:
            tip += f" · доступно {_state.latest}"
    icon.icon = make_icon_image(color)
    icon.title = tip
    icon.menu = build_menu()


def poll_loop(icon: pystray.Icon) -> None:
    while True:
        try:
            refresh(icon)
        except Exception:
            pass
        time.sleep(300)


# ─────────────────────────────── действия меню ──────────────────────────

def _open_hud(icon, item):
    webbrowser.open(HUD_URL)
    with _state.lock:
        hud_up = _state.hud_up
    if not hud_up:
        run_jarvis_async(["hud", "start"], on_done=lambda c, o: refresh(icon))


def _open_brain(icon, item):
    webbrowser.open(f"{HUD_URL}/#brain")


def _open_voice(icon, item):
    open_terminal("jarvis")


def _brief(icon, item):
    open_terminal("jarvis brief")


def _hush(icon, item):
    run_jarvis_async(["hush"])


def _selftest(icon, item):
    open_terminal("jarvis selftest")


def _doctor_fix(icon, item):
    open_terminal("jarvis doctor --fix")


def _open_vault(icon, item):
    def done(code, out):
        os.startfile(str(Path.home() / "JARVIS"))
    run_jarvis_async(["vault", "init"], on_done=done)


def _wizard(icon, item):
    threading.Thread(target=first_run_wizard, kwargs={"force": True}, daemon=True).start()


def _logs(icon, item):
    open_terminal("jarvis logs")


def _open_config(icon, item):
    os.startfile(str(HERMES_HOME / "config.yaml"))


def _perms(icon, item):
    run_jarvis_async(["perms"])


def _github(icon, item):
    inst = read_json(JARVIS_HOME / "install.json")
    repo = inst.get("repo", "debug999-cyber/jarvis-hermes")
    webbrowser.open(f"https://github.com/{repo}")


def _quit(icon, item):
    icon.stop()


def _toggle_services(icon, item):
    with _state.lock:
        both_up = _state.hud_up and _state.api_up
    if both_up:
        run_jarvis_async(["hud", "stop"])
        run_jarvis_async(["gateway", "stop"], on_done=lambda c, o: refresh(icon))
    else:
        run_jarvis_async(["gateway", "start"])
        run_jarvis_async(["hud", "start"], on_done=lambda c, o: refresh(icon))


def _ask(icon, item):
    def worker():
        q = ask_text("JARVIS слушает", "Что у меня сегодня в календаре?")
        if not q:
            return
        code, out = run_jarvis(["ask", q], timeout=120)
        notify("JARVIS", out.strip()[-400:] or "(нет ответа)")
    threading.Thread(target=worker, daemon=True).start()


def _check_updates(icon, item):
    def worker():
        code, out = run_jarvis(["update", "--check"], timeout=60)
        refresh(icon)
        if "недоступн" in out.lower() or "error" in out.lower():
            notify("JARVIS", f"Не удалось проверить обновления: {out.strip()[:200]}")
        else:
            with _state.lock:
                if _state.update_available:
                    notify("JARVIS", f"Доступно обновление {_state.latest}")
                else:
                    notify("JARVIS", f"У вас последняя версия {_state.version}")
    threading.Thread(target=worker, daemon=True).start()


def _do_update(icon, item):
    with _state.lock:
        _state.updating = True
    paint(icon)

    def worker():
        code, out = run_jarvis(["update", "--yes"], timeout=900)
        with _state.lock:
            _state.updating = False
        refresh(icon)
        if code == 0:
            notify("JARVIS обновлён", "Сервисы перезапущены. Откат — в меню.")
        else:
            notify("JARVIS: обновление не удалось", out.strip()[-300:])
    threading.Thread(target=worker, daemon=True).start()


def _rollback(icon, item):
    def worker():
        if not confirm("Откатить JARVIS на предыдущую версию?", "Это отменит последнее обновление."):
            return
        code, out = run_jarvis(["update", "--rollback"], timeout=120)
        refresh(icon)
        notify("JARVIS", "Откат выполнен" if code == 0 else f"Откат не удался: {out.strip()[:200]}")
    threading.Thread(target=worker, daemon=True).start()


def build_menu() -> pystray.Menu:
    with _state.lock:
        st = (f"JARVIS {_state.version}  ·  HUD {'●' if _state.hud_up else '○'}  "
              f"API {'●' if _state.api_up else '○'}")
        updating = _state.updating
        update_available = _state.update_available
        latest = _state.latest
        both_up = _state.hud_up and _state.api_up

    items = [pystray.MenuItem(st, None, enabled=False)]
    if updating:
        items.append(pystray.MenuItem("Обновление выполняется…", None, enabled=False))
    elif update_available:
        items.append(pystray.MenuItem(f"⬆ Обновить до {latest}", _do_update))
    items += [
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Открыть HUD", _open_hud, default=True),
        pystray.MenuItem("Голосовой чат в PowerShell", _open_voice),
        pystray.MenuItem("Спросить…", _ask),
        pystray.MenuItem("База знаний (BRAIN)", _open_brain),
        pystray.MenuItem("Замолчать", _hush),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Остановить сервисы" if both_up else "Запустить сервисы", _toggle_services),
        pystray.MenuItem("Утренний брифинг сейчас", _brief),
        pystray.MenuItem("Проверить интеграции (selftest)", _selftest),
        pystray.MenuItem("Диагностика и починка (doctor --fix)", _doctor_fix),
        pystray.MenuItem("Папка файлов %USERPROFILE%\\JARVIS", _open_vault),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Проверить обновления", _check_updates),
        pystray.MenuItem("Откатить последнее обновление", _rollback),
        pystray.MenuItem("Настройки (config.yaml)", _open_config),
        pystray.MenuItem("Параметры Windows (микрофон/уведомления/тихий час)", _perms),
        pystray.MenuItem("Логи", _logs),
        pystray.MenuItem("Мастер настройки…", _wizard),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Открыть на GitHub", _github),
        pystray.MenuItem("Выйти из JARVIS", _quit),
    ]
    return pystray.Menu(*items)


def setup(icon: pystray.Icon) -> None:
    icon.visible = True
    run_jarvis_async(["gateway", "start"])
    run_jarvis_async(["hud", "start"])
    refresh(icon)
    threading.Thread(target=poll_loop, args=(icon,), daemon=True).start()
    threading.Timer(0.5, first_run_wizard).start()


def main() -> int:
    global _icon
    if not IS_WINDOWS:
        print("jarvis_tray.pyw предназначен только для Windows", file=sys.stderr)
        return 1
    _icon = pystray.Icon("jarvis", make_icon_image(COLOR_OFF), "JARVIS", menu=build_menu())
    _icon.run(setup=setup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
