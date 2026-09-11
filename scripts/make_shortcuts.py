#!/usr/bin/env python3
"""
Быстрые команды JARVIS — на macOS это Shortcuts.app (.shortcut), на Windows —
пара .ps1-скриптов + .lnk-ярлыки на Рабочем столе и в «Отправить» (SendTo),
которые делают то же самое без сторонних зависимостей (только PowerShell,
он есть на любой Windows 10/11).

    jarvis shortcuts                                   собрать и разложить по местам
    python3 scripts/make_shortcuts.py --out ...         только файлы, без установки .lnk

Команды (Windows; все зовут %HERMES_HOME%\\bin\\jarvis.ps1, ничего больше):
  «Спросить JARVIS.lnk»        — окно ввода вопроса → ответ всплывающим уведомлением
  «JARVIS брифинг.lnk»         — утренний брифинг в открытом окне PowerShell
  «JARVIS замолчать.lnk»       — остановить речь (без окна, на двойной клик/по клавише)
  «В хранилище JARVIS» (SendTo)— выбранные файлы через правый клик → Отправить → копируются в vault/inbox
  «JARVIS heartbeat.lnk»       — тихая проверка «нужно ли что-то сказать?» (для Планировщика заданий)
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import uuid
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

IS_WINDOWS = sys.platform == "win32"

JARVIS = "$HOME/.local/bin/jarvis"
ENV = 'export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"; [ -f "$HOME/.jarvis-home" ] && export HERMES_HOME="$(cat "$HOME/.jarvis-home")"; '


def shell(script: str, input_mode: str = "as arguments", uid: str | None = None) -> dict:
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.runshellscript",
        "WFWorkflowActionParameters": {
            "Shell": "/bin/zsh", "Script": ENV + script, "InputMode": input_mode,
            "Input": {"Value": {"Type": "ExtensionInput"}, "WFSerializationType": "WFTextTokenAttachment"},
            "UUID": uid or str(uuid.uuid4()).upper(),
        },
    }


def ask(prompt: str) -> dict:
    return {"WFWorkflowActionIdentifier": "is.workflow.actions.ask",
            "WFWorkflowActionParameters": {"WFAskActionPrompt": prompt, "WFInputType": "Text", "WFAllowsMultilineText": False}}


def show_result() -> dict:
    return {"WFWorkflowActionIdentifier": "is.workflow.actions.showresult",
            "WFWorkflowActionParameters": {"Text": {"Value": {"attachmentsByRange": {"{0, 1}": {"Type": "ExtensionInput"}}, "string": "\ufffc"},
                                                    "WFSerializationType": "WFTextTokenString"}}}


def notification(title: str) -> dict:
    return {"WFWorkflowActionIdentifier": "is.workflow.actions.notification",
            "WFWorkflowActionParameters": {"WFNotificationActionTitle": title, "WFNotificationActionSound": False,
                                           "WFNotificationActionBody": {"Value": {"attachmentsByRange": {"{0, 1}": {"Type": "ExtensionInput"}}, "string": "\ufffc"},
                                                                        "WFSerializationType": "WFTextTokenString"}}}


def workflow(actions: list[dict], input_types: list[str] | None = None, color: int = 4282601983, glyph: int = 59511,
             quick_action: bool = False) -> dict:
    wf = {
        "WFWorkflowClientVersion": "2605.0.5", "WFWorkflowMinimumClientVersion": 900, "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": color, "WFWorkflowIconGlyphNumber": glyph},
        "WFWorkflowActions": actions,
        "WFWorkflowInputContentItemClasses": input_types or ["WFStringContentItem"],
        "WFWorkflowTypes": ["NCWidget", "WatchKit"] + (["QuickActions", "ActionExtension"] if quick_action else []),
        "WFWorkflowHasShortcutInputVariables": bool(input_types),
        "WFWorkflowHasOutputFallback": False, "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowImportQuestions": [], "WFQuickActionSurfaces": ["Finder", "ServicesMenu"] if quick_action else [],
    }
    return wf


SHORTCUTS = {
    "Спросить JARVIS": workflow([
        ask("Что спросить у JARVIS?"),
        shell(f'{JARVIS} ask "$@" 2>/dev/null | tail -c 1500'),
        notification("JARVIS"), show_result(),
    ], glyph=59511),
    "JARVIS брифинг": workflow([shell(f'open -a Terminal; sleep 0.5; osascript -e \'tell application "Terminal" to do script "{JARVIS} brief"\' >/dev/null')], glyph=59761),
    "JARVIS замолчать": workflow([shell(f"{JARVIS} hush >/dev/null 2>&1; echo ok")], glyph=59695, color=4292093695),
    "В хранилище JARVIS": workflow([
        shell('mkdir -p "$HOME/JARVIS/inbox"; n=0; for f in "$@"; do [ -e "$f" ] && cp -R "$f" "$HOME/JARVIS/inbox/" && n=$((n+1)); done; '
              f'{JARVIS} vault reindex >/dev/null 2>&1; echo "В хранилище JARVIS: $n файл(ов)"'),
        notification("JARVIS"),
    ], input_types=["WFGenericFileContentItem", "WFImageContentItem", "WFPDFContentItem", "WFRichTextContentItem", "WFURLContentItem"],
       quick_action=True, glyph=59446, color=4271458815),
    "JARVIS heartbeat": workflow([shell(f'{JARVIS} heartbeat 2>/dev/null | tail -c 500 | grep -v "^NO_REPLY$" || true'), notification("JARVIS")], glyph=59731),
}


def build(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for name, wf in SHORTCUTS.items():
        p = out / f"{name}.shortcut"
        with open(p, "wb") as f:
            plistlib.dump(wf, f, fmt=plistlib.FMT_BINARY)
        files.append(p)
    return files


def sign_and_import(files: list[Path]) -> int:
    if sys.platform != "darwin" or not shutil.which("shortcuts"):
        print("Подпись и импорт возможны только на macOS 12+ (команда `shortcuts`). Файлы собраны:", *files, sep="\n  ")
        return 0
    signed_dir = files[0].parent / "signed"
    signed_dir.mkdir(exist_ok=True)
    ok = 0
    for p in files:
        dst = signed_dir / p.name
        r = subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", str(p), "--output", str(dst)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 or not dst.exists():
            print(f"  ✖ {p.name}: не подписалась ({(r.stderr or r.stdout).strip()[:120]})")
            continue
        ok += 1
        subprocess.run(["open", str(dst)], check=False)  # Shortcuts.app покажет «Добавить быструю команду»
    print(f"  ✔ подписано {ok}/{len(files)} — подтвердите добавление в открывшихся окнах Shortcuts.")
    print("  Siri: «Запусти Спросить JARVIS». Finder: правый клик на файле → Быстрые действия → В хранилище JARVIS.")
    return 0 if ok else 1


# ─────────────────────────────── Windows ────────────────────────────────

_HERMES_HOME_WIN = os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home())), "hermes")

_PS_ASK = r"""
$question = [Microsoft.VisualBasic.Interaction]::InputBox('Что спросить у JARVIS?', 'JARVIS')
if (-not $question) { exit }
Add-Type -AssemblyName Microsoft.VisualBasic
$env:HERMES_HOME = '{home}'
$answer = & '{jarvis}' ask $question 2>$null
if ($answer) { $answer = $answer.Substring(0, [Math]::Min(1500, $answer.Length)) } else { $answer = '(нет ответа)' }
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip(8000, 'JARVIS', $answer, [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds 8
$n.Dispose()
"""

_PS_BRIEF = r"""
$env:HERMES_HOME = '{home}'
& '{jarvis}' brief
Write-Host ''
Read-Host 'Нажмите Enter, чтобы закрыть'
"""

_PS_HUSH = r"""
$env:HERMES_HOME = '{home}'
& '{jarvis}' hush *> $null
"""

_PS_VAULT = r"""
param([Parameter(ValueFromRemainingArguments = $true)]$Files)
$env:HERMES_HOME = '{home}'
$inbox = Join-Path $env:USERPROFILE 'JARVIS\inbox'
New-Item -ItemType Directory -Force -Path $inbox | Out-Null
$n = 0
foreach ($f in $Files) { if (Test-Path $f) { Copy-Item -Path $f -Destination $inbox -Recurse -Force; $n++ } }
& '{jarvis}' vault reindex *> $null
Add-Type -AssemblyName System.Windows.Forms
$ni = New-Object System.Windows.Forms.NotifyIcon
$ni.Icon = [System.Drawing.SystemIcons]::Information
$ni.Visible = $true
$ni.ShowBalloonTip(5000, 'JARVIS', "В хранилище JARVIS: $n файл(ов)", [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds 5
$ni.Dispose()
"""

_PS_HEARTBEAT = r"""
$env:HERMES_HOME = '{home}'
$reply = & '{jarvis}' heartbeat 2>$null
if ($reply -and $reply.Trim() -ne 'NO_REPLY') {
    Add-Type -AssemblyName System.Windows.Forms
    $n = New-Object System.Windows.Forms.NotifyIcon
    $n.Icon = [System.Drawing.SystemIcons]::Information
    $n.Visible = $true
    $n.ShowBalloonTip(6000, 'JARVIS', $reply.Substring(0, [Math]::Min(500, $reply.Length)), [System.Windows.Forms.ToolTipIcon]::Info)
    Start-Sleep -Seconds 6
    $n.Dispose()
}
"""

_WIN_SCRIPTS = {
    "ask-jarvis.ps1": (_PS_ASK, {}),
    "jarvis-brief.ps1": (_PS_BRIEF, {}),
    "jarvis-hush.ps1": (_PS_HUSH, {}),
    "jarvis-vault-inbox.ps1": (_PS_VAULT, {}),
    "jarvis-heartbeat.ps1": (_PS_HEARTBEAT, {}),
}

# .lnk name → (script filename, показывать окно?, аргументы после скрипта)
_WIN_LINKS = {
    "Спросить JARVIS.lnk": ("ask-jarvis.ps1", False, ""),
    "JARVIS брифинг.lnk": ("jarvis-brief.ps1", True, ""),
    "JARVIS замолчать.lnk": ("jarvis-hush.ps1", False, ""),
    "JARVIS heartbeat.lnk": ("jarvis-heartbeat.ps1", False, ""),
}
_SENDTO_LINK = ("В хранилище JARVIS.lnk", "jarvis-vault-inbox.ps1")


def build_windows(out: Path, home: str) -> list[Path]:
    scripts_dir = out / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    jarvis = str(Path(home) / "bin" / "jarvis.ps1")
    files = []
    for name, (tpl, _extra) in _WIN_SCRIPTS.items():
        p = scripts_dir / name
        p.write_text(tpl.format(home=home, jarvis=jarvis), encoding="utf-8")
        files.append(p)
    return files


def _make_lnk(link_path: Path, ps1: Path, hidden: bool) -> bool:
    """Создать .lnk через WScript.Shell (единственный надёжный способ без pywin32)."""
    style = 7 if hidden else 1  # 7 = minimized/hidden-ish, 1 = normal window
    ps = (
        "$W = New-Object -ComObject WScript.Shell; "
        f"$s = $W.CreateShortcut('{link_path}'); "
        "$s.TargetPath = (Get-Command powershell.exe).Source; "
        f"$s.Arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File \"{ps1}\"'; "
        f"$s.WindowStyle = {style}; $s.IconLocation = 'shell32.dll,220'; $s.Save()"
    )
    r = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return r.returncode == 0 and link_path.exists()


def install_windows(scripts: list[Path], scripts_dir: Path) -> int:
    if not IS_WINDOWS:
        print("Ярлыки Windows (.lnk) можно установить только на Windows. Скрипты собраны в:", scripts_dir)
        return 0
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    sendto = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "SendTo"
    ok, total = 0, 0
    for link_name, (script_name, hidden, _args) in _WIN_LINKS.items():
        total += 1
        if _make_lnk(desktop / link_name, scripts_dir / script_name, hidden):
            ok += 1
        else:
            print(f"  ✖ {link_name}: не удалось создать ярлык")
    sendto_name, sendto_script = _SENDTO_LINK
    if sendto.exists():
        total += 1
        if _make_lnk(sendto / sendto_name, scripts_dir / sendto_script, hidden=True):
            ok += 1
        else:
            print(f"  ✖ {sendto_name}: не удалось создать ярлык в SendTo")
    print(f"  ✔ установлено {ok}/{total} ярлыков на Рабочий стол и в «Отправить» (SendTo).")
    print("  Для heartbeat по расписанию зарегистрируйте Scheduled Task на jarvis-heartbeat.ps1 (см. install.ps1).")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    default_out = (os.path.join(_HERMES_HOME_WIN, "jarvis", "shortcuts") if IS_WINDOWS
                   else os.path.expanduser("~/Library/Application Support/JARVIS/shortcuts"))
    ap.add_argument("--out", default=default_out)
    ap.add_argument("--home", default=_HERMES_HOME_WIN, help="HERMES_HOME (Windows only)")
    ap.add_argument("--no-import", action="store_true", help="только собрать файлы, не устанавливать")
    a = ap.parse_args(argv)
    out = Path(a.out).expanduser()

    if IS_WINDOWS:
        files = build_windows(out, a.home)
        if a.no_import:
            print(*files, sep="\n")
            return 0
        return install_windows(files, out / "scripts")

    files = build(out)
    if a.no_import:
        print(*files, sep="\n")
        return 0
    return sign_and_import(files)


if __name__ == "__main__":
    sys.exit(main())
