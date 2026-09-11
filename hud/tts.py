"""
Серверный синтез речи для HUD — тот же голос, что в voice mode Hermes.

Порядок движков (первый доступный):
  1. edge-tts (python-модуль из venv Hermes; ставится вместе с `[voice]`)  → mp3, голос из config.yaml → tts.edge.voice
  2. edge-tts CLI (`edge-tts --text … --write-media …`)                      → mp3
  3. macOS `say` (голос Milena/Yuri, встроен в систему)                      → m4a (AAC), играет во всех браузерах
  3b. Windows SAPI (System.Speech, встроен, без установки)                   → wav
  3c. Linux espeak-ng (офлайн, ставится install.linux.sh)                    → wav, роботизированный голос-фолбэк
  4. ничего → HUD сам озвучит браузерным speechSynthesis (как раньше)

Результат кэшируется по sha1(текст+голос) в $HERMES_HOME/cache/tts/ (последние 200 файлов), чтобы повторные фразы
(«Слушаю, сэр», подтверждения таймеров) не ходили в сеть.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
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

HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
CACHE_DIR = HERMES_HOME / "cache" / "tts"
MAX_CHARS = 1500
DEFAULT_VOICE = "ru-RU-DmitryNeural"
_MD = re.compile(r"[*_`#>]|\[(.*?)\]\(.*?\)")
_URL = re.compile(r"https?://\S+")


def _config_voice() -> tuple[str, float]:
    """tts.edge.voice и tts.speed из config.yaml Hermes (без PyYAML — простой построчный парсер)."""
    voice, speed, section = DEFAULT_VOICE, 1.0, []
    try:
        for raw in (HERMES_HOME / "config.yaml").read_text(encoding="utf-8").splitlines():
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip())
            key, _, val = raw.strip().partition(":")
            section = section[: indent // 2] + [key]
            val = val.split("#", 1)[0].strip().strip('"').strip("'")
            if section == ["tts", "edge", "voice"] and val:
                voice = val
            elif section == ["tts", "speed"] and val:
                try:
                    speed = float(val)
                except ValueError:
                    pass
    except OSError:
        pass
    return voice, speed


def clean(text: str) -> str:
    text = _URL.sub("ссылка", text)
    text = _MD.sub(lambda m: m.group(1) or "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CHARS]


def engine() -> str:
    try:
        import edge_tts  # noqa: F401
        return "edge-tts"
    except ImportError:
        pass
    if shutil.which("edge-tts"):
        return "edge-tts-cli"
    if sys.platform == "darwin" and shutil.which("say"):
        return "say"
    if sys.platform == "win32":
        return "sapi"
    if sys.platform.startswith("linux") and (shutil.which("espeak-ng") or shutil.which("espeak")):
        return "espeak"
    return "none"


def _edge_py(text: str, voice: str, speed: float, out: Path) -> bool:
    import edge_tts
    rate = f"{int(round((speed - 1) * 100)):+d}%"

    async def run():
        await edge_tts.Communicate(text, voice, rate=rate).save(str(out))

    try:
        asyncio.run(asyncio.wait_for(run(), timeout=20))
        return out.exists() and out.stat().st_size > 0
    except Exception:  # сеть/голос недоступны → пробуем следующий движок
        return False


def _edge_cli(text: str, voice: str, speed: float, out: Path) -> bool:
    rate = f"{int(round((speed - 1) * 100)):+d}%"
    try:
        subprocess.run(["edge-tts", "--voice", voice, "--rate", rate, "--text", text, "--write-media", str(out)],
                       check=True, capture_output=True, timeout=25)
        return out.exists() and out.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        return False


def _say(text: str, speed: float, out: Path) -> bool:
    voice = "Milena" if "Svetlana" in _config_voice()[0] else "Yuri"
    try:
        subprocess.run(["say", "-v", voice, "-r", str(int(175 * speed)), "-o", str(out),
                        "--file-format=m4af", "--data-format=aac", text], check=True, capture_output=True, timeout=30)
        return out.exists() and out.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        # голос может быть не установлен — системный по умолчанию
        try:
            subprocess.run(["say", "-o", str(out), "--file-format=m4af", "--data-format=aac", text],
                           check=True, capture_output=True, timeout=30)
            return out.exists() and out.stat().st_size > 0
        except (subprocess.SubprocessError, OSError):
            return False


def _espeak(text: str, speed: float, out: Path) -> bool:
    """espeak-ng (offline, всегда доступен на Linux после apt install espeak-ng) — заметно роботизированный
    голос, используется только когда edge-tts недоступен (нет сети/модуля)."""
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    wpm = max(80, min(400, int(175 * speed)))
    voice, _ = _config_voice()
    espeak_voice = "ru" if any(c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя" for c in voice.lower()) or "ru" in voice.lower() else "ru"
    try:
        subprocess.run([binary, "-v", espeak_voice, "-s", str(wpm), "-w", str(out), text],
                       check=True, capture_output=True, timeout=30)
        return out.exists() and out.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        return False


def _sapi(text: str, speed: float, out: Path) -> bool:
    """Windows SAPI (System.Speech) через PowerShell — встроен, без установки."""
    rate = max(-10, min(10, round((speed - 1) * 10)))
    esc = text.replace("'", "''")
    out_esc = str(out).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = {rate}; $s.SetOutputToWaveFile('{out_esc}'); $s.Speak('{esc}'); $s.Dispose()"
    )
    try:
        subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            check=True, capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return out.exists() and out.stat().st_size > 0
    except (subprocess.SubprocessError, OSError):
        return False


def _prune(keep: int = 200) -> None:
    files = sorted(CACHE_DIR.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


def synthesize(text: str) -> tuple[bytes, str] | None:
    """→ (audio_bytes, mime) или None, если ни один движок не сработал."""
    text = clean(text)
    if not text:
        return None
    voice, speed = _config_voice()
    eng = engine()
    if eng == "none":
        return None
    if eng == "say":
        ext, mime = "m4a", "audio/mp4"
    elif eng in ("sapi", "espeak"):
        ext, mime = "wav", "audio/wav"
    else:
        ext, mime = "mp3", "audio/mpeg"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{eng}|{voice}|{speed}|{text}".encode()).hexdigest()[:24]
    cached = CACHE_DIR / f"{key}.{ext}"
    if cached.exists() and cached.stat().st_size > 0:
        os.utime(cached)
        return cached.read_bytes(), mime
    # mkstemp() возвращает открытый файловый дескриптор — на Linux/macOS файл с открытым хендлом
    # спокойно переименовывается/удаляется, но на Windows это приводит к PermissionError
    # (WinError 32, «файл занят другим процессом») при tmp.replace(cached) ниже. Закрываем сразу.
    _tmp_fd, _tmp_name = tempfile.mkstemp(suffix=f".{ext}", dir=CACHE_DIR)
    os.close(_tmp_fd)
    tmp = Path(_tmp_name)
    ok = False
    if eng == "edge-tts":
        ok = _edge_py(text, voice, speed, tmp)
    if not ok and eng in ("edge-tts", "edge-tts-cli") and shutil.which("edge-tts"):
        ok = _edge_cli(text, voice, speed, tmp)
    if not ok and sys.platform == "darwin" and shutil.which("say"):
        ext, mime = "m4a", "audio/mp4"
        tmp2 = tmp.with_suffix(".m4a")
        ok = _say(text, speed, tmp2)
        tmp.unlink(missing_ok=True)
        tmp = tmp2
        cached = cached.with_suffix(".m4a")
    if not ok and eng == "sapi":
        ext, mime = "wav", "audio/wav"
        tmp2 = tmp.with_suffix(".wav")
        ok = _sapi(text, speed, tmp2)
        tmp.unlink(missing_ok=True)
        tmp = tmp2
        cached = cached.with_suffix(".wav")
    if not ok and eng == "espeak":
        ext, mime = "wav", "audio/wav"
        tmp2 = tmp.with_suffix(".wav")
        ok = _espeak(text, speed, tmp2)
        tmp.unlink(missing_ok=True)
        tmp = tmp2
        cached = cached.with_suffix(".wav")
    if not ok:
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(cached)
    _prune()
    return cached.read_bytes(), mime


if __name__ == "__main__":  # python3 hud/tts.py "текст" > out.mp3
    res = synthesize(" ".join(sys.argv[1:]) or "Слушаю, сэр.")
    if not res:
        print(f"нет движка TTS (engine={engine()})", file=sys.stderr)
        sys.exit(1)
    sys.stdout.buffer.write(res[0])
