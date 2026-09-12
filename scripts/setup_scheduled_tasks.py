#!/usr/bin/env python3
"""
Регистрация автозапуска JARVIS в Планировщике заданий Windows — аналог
config/launchd/*.plist на macOS. Не требует прав администратора: задачи
регистрируются для текущего пользователя (/RL LIMITED, триггер "при входе").

Соответствие launchd → Scheduled Tasks:
  ai.jarvis.hud.plist      → JARVIS-HUD       (при входе + перезапуск при сбое, как KeepAlive)
  ai.jarvis.gateway.plist  → JARVIS-Gateway   (при входе + перезапуск при сбое, как KeepAlive)
  ai.jarvis.updater.plist  → JARVIS-Updater   (ежедневно в 11:15, как StartCalendarInterval)
  ai.jarvis.app.plist      → JARVIS-App       (при входе, открывает трей-приложение)

Использование:
  python3 setup_scheduled_tasks.py install --home ... --python ... [--no-app] [--no-cron]
  python3 setup_scheduled_tasks.py remove
  python3 setup_scheduled_tasks.py status
"""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import tempfile
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

TASKS = ("JARVIS-HUD", "JARVIS-Gateway", "JARVIS-Updater", "JARVIS-App")

# Task Scheduler XML — RestartOnFailure даёт то же, что launchd KeepAlive+ThrottleInterval:
# при падении процесс перезапускается, каждые ~1 минуту.
# ВАЖНО: элемент Count в схеме Task Scheduler (и в MS-TSCH 2.5.4.2) имеет тип unsignedByte —
# допустимый диапазон 1..255. Раньше здесь стояло 999 — это вне схемы, и schtasks.exe
# отвергал такой XML целиком, но выводил при этом обманчивую ошибку "Отказано в доступе"
# вместо внятного сообщения о невалидной схеме. Из-за этого регистрировались только задачи
# БЕЗ RestartOnFailure (JARVIS-Updater), а HUD/Gateway/App (restart=True) падали с
# "Access is denied" — что и было замечено пользователем как проблему с правами.
_TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>{triggers}</Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    {restart}
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

_TRIGGER_LOGON = "<LogonTrigger><Enabled>true</Enabled></LogonTrigger>"
_TRIGGER_DAILY = ("<CalendarTrigger><StartBoundary>{date}T{time}:00</StartBoundary>"
                   "<Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger>")
_RESTART_ON_FAILURE = "<RestartOnFailure><Interval>PT1M</Interval><Count>255</Count></RestartOnFailure>"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    # schtasks.exe — консольная программа: она пишет stdout/stderr в кодировке OEM-кодовой
    # страницы консоли (GetOEMCP(), напр. cp866 для русской локали), а НЕ в ANSI-кодировке
    # (GetACP(), напр. cp1251) и уж тем более не в UTF-8. Раньше здесь стояло encoding="utf-8":
    # это не падало (errors="replace" глотал ошибки декодирования), но результат превращался
    # в нечитаемую кашу (напр. "ОШИБКА: Отказано в доступе." → "������: �⪠���� � ����㯥.")
    # вместо настоящего текста ошибки. Python начиная с 3.6 имеет отдельный кодек "oem" именно
    # для этого случая (https://bugs.python.org/issue27959) — используем его на Windows.
    kw.setdefault("encoding", "oem" if sys.platform == "win32" else "utf-8")
    kw.setdefault("errors", "replace")
    kw.setdefault("timeout", 30)
    if sys.platform == "win32":
        kw.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(cmd, **kw)


def _register(name: str, description: str, command: str, arguments: str, workdir: str,
              user: str, trigger_xml: str, restart: bool) -> tuple[bool, str]:
    xml = _TASK_XML.format(
        description=description, triggers=trigger_xml, user=user,
        restart=_RESTART_ON_FAILURE if restart else "",
        command=command, arguments=arguments, workdir=workdir,
    )
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
        f.write(xml)
        path = f.name
    try:
        r = _run(["schtasks", "/Create", "/TN", name, "/XML", path, "/F"])
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    finally:
        os.unlink(path)


def install(home: str, python_exe: str, no_app: bool, no_cron: bool) -> int:
    user = f"{os.environ.get('USERDOMAIN', '.')}\\{getpass.getuser()}"
    jarvis_home = str(Path(home) / "jarvis")
    hermes_bin = str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "bin" / "hermes.exe")
    if not Path(hermes_bin).exists():
        hermes_bin = "hermes.exe"  # полагаемся на PATH, если явный путь не найден

    ok_all = True

    ok, msg = _register(
        "JARVIS-HUD", "JARVIS HUD (веб-панель) — автозапуск при входе",
        python_exe, f'"{jarvis_home}\\hud\\server.py" --port 8765', home, user, _TRIGGER_LOGON, restart=True,
    )
    print(f"  {'✔' if ok else '✖'} JARVIS-HUD" + ("" if ok else f": {msg}"))
    ok_all &= ok

    ok, msg = _register(
        "JARVIS-Gateway", "JARVIS gateway (Telegram/Discord/API) — автозапуск при входе",
        hermes_bin, "gateway run", home, user, _TRIGGER_LOGON, restart=True,
    )
    print(f"  {'✔' if ok else '✖'} JARVIS-Gateway" + ("" if ok else f": {msg}"))
    ok_all &= ok

    if not no_cron:
        ok, msg = _register(
            "JARVIS-Updater", "JARVIS: ежедневная проверка обновлений",
            python_exe, f'"{jarvis_home}\\update.py" auto', home, user,
            _TRIGGER_DAILY.format(date="2024-01-01", time="11:15"), restart=False,
        )
        print(f"  {'✔' if ok else '✖'} JARVIS-Updater" + ("" if ok else f": {msg}"))
        ok_all &= ok

    if not no_app:
        pyw = python_exe.replace("python.exe", "pythonw.exe")
        if not Path(pyw).exists():
            pyw = python_exe
        ok, msg = _register(
            "JARVIS-App", "JARVIS — значок в системном трее",
            pyw, f'"{jarvis_home}\\tray\\jarvis_tray.pyw"', home, user, _TRIGGER_LOGON, restart=True,
        )
        print(f"  {'✔' if ok else '✖'} JARVIS-App" + ("" if ok else f": {msg}"))
        ok_all &= ok

    return 0 if ok_all else 1


def remove() -> int:
    ok_all = True
    for name in TASKS:
        r = _run(["schtasks", "/Delete", "/TN", name, "/F"])
        found = r.returncode == 0
        if found:
            print(f"  ✔ {name} удалена")
        else:
            print(f"  · {name} не была установлена")
    return 0 if ok_all else 1


def status() -> int:
    r = _run(["schtasks", "/Query", "/FO", "LIST"])
    out = r.stdout or ""
    found = [t for t in TASKS if t in out]
    for t in TASKS:
        print(f"  {'✔' if t in found else '✖'} {t}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_install = sub.add_parser("install")
    p_install.add_argument("--home", required=True)
    p_install.add_argument("--python", required=True)
    p_install.add_argument("--no-app", action="store_true")
    p_install.add_argument("--no-cron", action="store_true")
    sub.add_parser("remove")
    sub.add_parser("status")
    args = ap.parse_args()

    if sys.platform != "win32":
        print("setup_scheduled_tasks.py предназначен только для Windows", file=sys.stderr)
        return 1

    if args.cmd == "install":
        return install(args.home, args.python, args.no_app, args.no_cron)
    if args.cmd == "remove":
        return remove()
    return status()


if __name__ == "__main__":
    sys.exit(main())
