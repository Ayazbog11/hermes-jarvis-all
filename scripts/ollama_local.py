#!/usr/bin/env python3
"""
`jarvis ollama` — управление локальными моделями Ollama напрямую из JARVIS,
без похода в `hermes model` вслепую.

Почему это лучше, чем просто "откройте hermes model и разберитесь сами"
(как было раньше в трее/меню-баре): Ollama даёт HTTP API на 127.0.0.1:11434
(https://github.com/ollama/ollama/blob/main/docs/api.md) — можно узнать, запущен ли
он, что уже скачано, скачать модель с прогрессом и сразу прописать её в config.yaml
Hermes (в $HERMES_HOME) через официальный `hermes config set` (а не руками редактировать
YAML — так не сломать формат, который поддерживает Hermes сам).

Команды:
  jarvis ollama status              — установлен/запущен ли Ollama, какие модели скачаны, что выбрано в Hermes
  jarvis ollama list                — только список скачанных моделей
  jarvis ollama pull <модель>       — скачать модель (напр. qwen3:8b, llama3.1:8b, qwen2.5vl:7b для зрения)
  jarvis ollama use <модель> [--context N] [--vision] [--no-verify]
                                     — прописать модель в Hermes: model.provider=custom,
                                       model.base_url=http://127.0.0.1:11434/v1, model.default=<модель>.
                                       --vision вместо основной модели настраивает auxiliary.vision
                                       (отдельная модель для распознавания экрана/фото — см. docs/AI-MODELS.md).
                                       По умолчанию после переключения ОДИН РАЗ проверяется, что модель
                                       реально отвечает (`hermes chat -q ...`); если нет — конфигурация
                                       автоматически откатывается на значения ДО переключения (safe-switch,
                                       --no-verify отключает эту проверку).
  jarvis ollama recommend           — напечатать 2-3 модели, которые стоит попробовать (баланс/зрение), с командой pull

Работает без ключей и без интернета (кроме самого шага pull, который качает модель один раз).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

if sys.platform == "win32":  # pragma: no cover — покрыто CI на windows-latest
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "").strip() or "http://127.0.0.1:11434"
if not OLLAMA_HOST.startswith(("http://", "https://")):
    OLLAMA_HOST = f"http://{OLLAMA_HOST}"
BASE_URL_FOR_HERMES = OLLAMA_HOST.rstrip("/") + "/v1"

# Рекомендации: маленькая универсальная модель, модель побольше для качества, модель для зрения.
# Ollama сам подбирает размер квантизации под доступную VRAM/RAM при `ollama pull <имя без тега>`.
RECOMMENDED = [
    ("qwen3:8b", "универсальная, быстрая, хороша на CPU/8ГБ+ VRAM"),
    ("llama3.1:8b", "альтернатива, чуть слабее в тулкол-режиме, чем qwen3"),
    ("qwen2.5vl:7b", "модель с поддержкой зрения (для auxiliary.vision — распознавание экрана/фото)"),
    ("nomic-embed-text", "маленькая (~270 МБ) модель эмбеддингов — включает семантический поиск по хранилищу "
                         "(jarvis vault): находит документы по смыслу, а не только по совпадению слов"),
]


def _get(path: str, timeout: float = 3.0) -> dict:
    req = urllib.request.Request(OLLAMA_HOST.rstrip("/") + path)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def is_running() -> bool:
    try:
        _get("/api/tags", timeout=1.5)
        return True
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return False


def list_models() -> list[dict]:
    try:
        data = _get("/api/tags")
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return []
    return data.get("models", [])


def ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def pull(model: str) -> int:
    """Стримит прогресс `ollama pull` через CLI (надёжнее, чем парсить NDJSON API вручную;

    если сам бинарник ollama недоступен в PATH — используем HTTP API как запасной путь).
    """
    if shutil.which("ollama"):
        proc = subprocess.run(["ollama", "pull", model])
        return proc.returncode
    # запасной путь — HTTP API (NDJSON stream)
    try:
        req = urllib.request.Request(
            OLLAMA_HOST.rstrip("/") + "/api/pull",
            data=json.dumps({"name": model}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1800) as r:
            for line in r:
                try:
                    evt = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                status = evt.get("status", "")
                if status:
                    print(status)
        return 0
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        print(f"✖ не удалось скачать модель: {e}", file=sys.stderr)
        return 1


def hermes_config_set(key: str, value: str) -> bool:
    try:
        subprocess.run(["hermes", "config", "set", key, value], check=True,
                        capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        print(f"✖ hermes config set {key} {value} — {e}", file=sys.stderr)
        return False


def hermes_config_get(key: str) -> str:
    try:
        out = subprocess.run(["hermes", "config", "get", key], check=True,
                              capture_output=True, text=True).stdout.strip()
        return out
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def cmd_status(_args: argparse.Namespace) -> int:
    if not ollama_installed():
        print("✖ Ollama не найден в PATH. Установите: https://ollama.com/download")
        return 1
    running = is_running()
    print(f"Ollama: установлен, {'запущен' if running else 'НЕ запущен (запустите приложение Ollama или `ollama serve`)'}")
    if running:
        models = list_models()
        if models:
            print(f"Скачанные модели ({len(models)}):")
            names = set()
            for m in models:
                size_gb = (m.get("size") or 0) / (1024 ** 3)
                print(f"  - {m.get('name', '?')}  ({size_gb:.1f} ГБ)")
                names.add(m.get("name", "").split(":")[0])
            if "nomic-embed-text" in names:
                print("Семантический поиск по хранилищу (jarvis vault) включён (nomic-embed-text найдена).")
            else:
                print("Семантический поиск по хранилищу выключен — нет nomic-embed-text (jarvis ollama pull nomic-embed-text).")
        else:
            print("Моделей ещё нет. Смотрите: jarvis ollama recommend")
    current_provider = hermes_config_get("model.provider")
    current_model = hermes_config_get("model.default")
    current_base = hermes_config_get("model.base_url")
    if current_provider == "custom" and "11434" in current_base:
        print(f"Hermes сейчас использует локальную модель через Ollama: {current_model}")
    else:
        print(f"Hermes сейчас использует: provider={current_provider or '—'} model={current_model or '—'}")
    vision_base = hermes_config_get("auxiliary.vision.base_url")
    vision_model = hermes_config_get("auxiliary.vision.model")
    if "11434" in vision_base:
        print(f"Модель для зрения (auxiliary.vision) — тоже локальная через Ollama: {vision_model}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    if not is_running():
        print("✖ Ollama не запущен", file=sys.stderr)
        return 1
    for m in list_models():
        print(m.get("name", "?"))
    return 0


def cmd_recommend(_args: argparse.Namespace) -> int:
    print("Рекомендуемые локальные модели (скачиваются один раз, дальше работают офлайн):\n")
    for name, note in RECOMMENDED:
        print(f"  jarvis ollama pull {name:<16} # {note}")
    print("\nПосле скачивания:")
    print("  jarvis ollama use qwen3:8b            # как основную модель чата")
    print("  jarvis ollama use qwen2.5vl:7b --vision  # как отдельную модель для зрения")
    print("  jarvis ollama pull nomic-embed-text       # включает семантический поиск по хранилищу (jarvis vault),")
    print("                                             # ничего прописывать в конфиг не нужно — находится сама")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    if not ollama_installed() and not is_running():
        print("✖ Ollama не установлен и не запущен. Установите: https://ollama.com/download", file=sys.stderr)
        return 1
    print(f"Скачиваю {args.model}… (может занять несколько минут в зависимости от размера)")
    return pull(args.model)


def ping_model(timeout: float = 60.0) -> tuple[bool, str]:
    """Проверить, что модель, прописанная СЕЙЧАС в Hermes, реально отвечает.

    Та же эвристика, что и scripts/doctor.py:check_model() — одна короткая реплика
    и проверка на явные признаки ошибки (HTTP-коды, traceback, пустой ответ).
    """
    try:
        proc = subprocess.run(["hermes", "chat", "-q", "Ответь одним словом: ok"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"hermes chat не запустился: {e}"
    text = (proc.stdout or "").strip()
    low = text.lower()
    if proc.returncode != 0 or not text or any(k in low for k in ("error code", "http 4", "http 5", "traceback", "401", "403", "405", "429")):
        return False, (text[-160:] or "пустой ответ")
    return True, text[:160]


def cmd_use(args: argparse.Namespace) -> int:
    """Переключить модель Hermes на локальную через Ollama.

    Безопасность (аудит GitHub, Раунд 7 — паттерн model-watchdog: снимок конфигурации перед
    изменением, проверка здоровья, автооткат при отказе, без внешних зависимостей): перед
    записью новых значений снимается снимок текущих ключей config.yaml; после записи (если
    не --no-verify и не --vision — для vision-модели «пинг» текстовым чатом не показателен)
    Hermes реально спрашивается один раз; если ответ похож на ошибку — все изменённые ключи
    откатываются на снятые значения и команда завершается с ошибкой, а НЕ оставляет Hermes
    с нерабочей моделью до следующего случайного открытия чата пользователем.
    """
    if not is_running():
        print("✖ Ollama не запущен — сначала запустите приложение Ollama (или `ollama serve`)", file=sys.stderr)
        return 1
    names = {m.get("name") for m in list_models()}
    if args.model not in names and not args.skip_check:
        print(f"⚠ Модель {args.model!r} ещё не скачана. Скачиваю…")
        if pull(args.model) != 0:
            return 1

    if args.vision:
        keys = ["auxiliary.vision.base_url", "auxiliary.vision.api_key", "auxiliary.vision.model"]
        values = [BASE_URL_FOR_HERMES, "local-key", args.model]
    else:
        keys = ["model.provider", "model.base_url", "model.default"]
        values = ["custom", BASE_URL_FOR_HERMES, args.model]
        if args.context:
            keys.append("model.context_length")
            values.append(str(args.context))

    snapshot = {k: hermes_config_get(k) for k in keys}  # для отката — читаем ДО изменения

    ok = True
    for k, v in zip(keys, values, strict=True):
        if not hermes_config_set(k, v):
            ok = False
            break
    if not ok:
        print("✖ Не удалось записать конфигурацию — откатываю уже изменённые ключи…", file=sys.stderr)
        _restore_snapshot(snapshot)
        return 1

    verify = not args.no_verify and not args.vision  # для vision текстовый пинг ничего не проверяет
    if verify:
        print("Проверяю, что модель отвечает…")
        healthy, detail = ping_model()
        if not healthy:
            print(f"✖ Модель {args.model!r} не отвечает ({detail}) — откатываю конфигурацию на прежние значения…",
                  file=sys.stderr)
            _restore_snapshot(snapshot)
            print("✔ Откат выполнен, Hermes использует прежнюю модель.", file=sys.stderr)
            return 1
        print(f"✔ Модель отвечает: {detail}")

    if args.vision:
        print(f"✔ Модель для зрения (auxiliary.vision) теперь: {args.model} через Ollama ({BASE_URL_FOR_HERMES})")
    else:
        print(f"✔ Hermes теперь использует локальную модель {args.model} через Ollama ({BASE_URL_FOR_HERMES}).")
        print("  Перезапустите gateway/TUI, чтобы изменение подхватилось: jarvis gateway restart")
    return 0


def _restore_snapshot(snapshot: dict[str, str]) -> None:
    """Вернуть ключи config.yaml к значениям ДО попытки переключения модели.

    Пустая старая строка означает «ключ не был задан» — в этом случае Hermes'у нечего
    восстанавливать надёжным способом через `config set` (нет команды unset в этом CLI),
    поэтому такие ключи просто пропускаются с предупреждением: лучше оставить новое (уже
    записанное, но нерабочее) значение видимым пользователю, чем тихо потерять информацию
    о том, что откат был неполным.
    """
    for k, old in snapshot.items():
        if old:
            hermes_config_set(k, old)
        else:
            print(f"  (⚠ ключ {k} не был задан раньше — не откатываю, только что установленное значение останется)",
                  file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(prog="jarvis ollama", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("status", help="установлен/запущен ли Ollama, что скачано, что выбрано в Hermes").set_defaults(func=cmd_status)
    sub.add_parser("list", help="список скачанных моделей").set_defaults(func=cmd_list)
    sub.add_parser("recommend", help="какие модели попробовать").set_defaults(func=cmd_recommend)
    p_pull = sub.add_parser("pull", help="скачать модель")
    p_pull.add_argument("model")
    p_pull.set_defaults(func=cmd_pull)
    p_use = sub.add_parser("use", help="прописать модель в Hermes")
    p_use.add_argument("model")
    p_use.add_argument("--context", type=int, default=0, help="context_length (напр. 32768) — Ollama по умолчанию режет контекст")
    p_use.add_argument("--vision", action="store_true", help="настроить как auxiliary.vision, а не основную модель чата")
    p_use.add_argument("--skip-check", action="store_true", help="не проверять/не докачивать модель перед использованием")
    p_use.add_argument("--no-verify", action="store_true",
                        help="не проверять реальный ответ модели после переключения (без этого — по умолчанию проверяется, "
                             "и при отказе конфигурация автоматически откатывается на прежнюю модель)")
    p_use.set_defaults(func=cmd_use)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
