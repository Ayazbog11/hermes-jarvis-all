# ИИ: провайдер, ключи, модель для зрения, локальная модель

JARVIS не привязан к одному провайдеру ИИ — под капотом это настройки самого Hermes Agent
(`hermes model`, `config.yaml`), но мы вынесли самые частые действия в трей (Windows/Linux) и
меню-бар (macOS), плюс дали CLI для локальных моделей, которым не нужен ни ключ, ни мастер.

## 1. Провайдер и ключ основной модели чата

Пункт трея/меню-бара **«ИИ: ключи / модель / провайдер…»** открывает терминал и запускает
`hermes model` — это полный мастер Hermes: выбор провайдера (OpenRouter, Anthropic, OpenAI,
Google, Nous, кастомный OpenAI-совместимый endpoint и т.д.), ввод/генерация ключа, выбор
конкретной модели. Мастер сам пишет результат в `~/.hermes/config.yaml` (`model.*`) и
`~/.hermes/.env` (сам ключ) — вручную редактировать эти файлы не нужно.

Из терминала то же самое: `hermes model`. После смены модели — `jarvis gateway restart`,
чтобы Telegram/Discord/API-сервер подхватили новую модель (голосовой TUI подхватывает сразу).

## 2. Отдельная модель для зрения (vision)

Модель, которая распознаёт скриншоты/фото (`vision_analyze`, скриншоты браузера), **не обязана
совпадать** с основной моделью чата — так можно, например, использовать быструю дешёвую модель
для разговора и отдельную сильную vision-модель только для картинок. Настраивается в
`config.yaml` под ключом `auxiliary.vision`:

```yaml
auxiliary:
  vision:
    provider: "auto"          # auto | openrouter | nous | codex | main | anthropic…
    model: ""                 # напр. "openai/gpt-4o", "google/gemini-2.5-flash"
    base_url: ""              # свой OpenAI-совместимый endpoint (перекрывает provider)
    api_key: ""               # ключ для base_url (иначе — OPENAI_API_KEY)
```

Пункт трея/меню-бара **«ИИ: модель для зрения (vision)…»** открывает `config.yaml` прямо на
этом разделе. Локальную vision-модель через Ollama можно подключить одной командой —
см. раздел 3 ниже (`--vision`).

## 3. Локальная модель через Ollama — без ключа и без интернета

Раньше пункт «подключить локальную модель» просто открывал `hermes model` и просил пользователя
самому выбрать «Custom endpoint» и вспомнить адрес Ollama. Теперь это делает `jarvis ollama`
(`scripts/ollama_local.py`) — говорит с локальным Ollama API (`127.0.0.1:11434`,
[docs.ollama.com](https://github.com/ollama/ollama/blob/main/docs/api.md)) напрямую и сам
прописывает результат в Hermes через `hermes config set` (официальный способ менять
`config.yaml`, не руками).

```bash
jarvis ollama status              # установлен/запущен ли Ollama, что уже скачано, что выбрано в Hermes
jarvis ollama recommend           # какие модели попробовать
jarvis ollama pull qwen3:8b       # скачать модель (один раз, дальше офлайн)
jarvis ollama use qwen3:8b        # сделать её основной моделью чата
jarvis ollama use qwen2.5vl:7b --vision   # сделать её отдельной моделью для зрения (auxiliary.vision)
```

`jarvis ollama use` сам скачивает модель, если её ещё нет, и одной командой прописывает
`model.provider=custom`, `model.base_url=http://127.0.0.1:11434/v1`, `model.default=<модель>`
(либо соответствующие ключи `auxiliary.vision.*` с флагом `--vision`). Требуется установленный
и запущенный [Ollama](https://ollama.com/download) — сам JARVIS его не устанавливает.

Почему `--context` иногда нужен: Ollama по умолчанию режет контекст модели до 2–8К токенов
независимо от объявленного окна модели — если ответы начинают «забывать» начало длинного
разговора, задайте окно явно: `jarvis ollama use qwen3:8b --context 32768`.

Меню трея/меню-бара **«ИИ: подключить локальную модель (Ollama)…»** открывает терминал с
`jarvis ollama status` и `jarvis ollama recommend`, чтобы сразу увидеть текущее состояние и
рекомендации, не набирая команды вслепую.

## Сводка: что где настраивается

| Что | Команда/меню | Где хранится |
|---|---|---|
| Провайдер + ключ + модель чата | `hermes model` / трей «ИИ: ключи / модель / провайдер…» | `~/.hermes/config.yaml` (`model.*`), `~/.hermes/.env` |
| Модель для зрения | `jarvis ollama use <модель> --vision` (локально) или ручная правка `config.yaml` / трей «ИИ: модель для зрения…» | `~/.hermes/config.yaml` (`auxiliary.vision.*`) |
| Локальная модель (офлайн, без ключа) | `jarvis ollama pull/use` | Ollama (`~/.ollama/models`) + `~/.hermes/config.yaml` |
| Календарь | `jarvis calendar setup` | см. [docs/CALENDAR.md](CALENDAR.md) |
