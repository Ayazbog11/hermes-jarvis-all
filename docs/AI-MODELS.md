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

### Бонус: семантический поиск по памяти и файлам (`nomic-embed-text`)

```bash
jarvis ollama pull nomic-embed-text   # маленькая (~270 МБ) модель эмбеддингов
```

Если эта модель скачана, `brain_recall` (база знаний) и `vault_search` (хранилище файлов) начинают
искать не только по точным словам (BM25), но и по смыслу — находят перефразировки без общих слов
с вопросом. Ничего прописывать в конфиг не нужно: JARVIS сам обнаруживает модель и включает гибридный
поиск. Подробности и почему выбран именно этот подход — `docs/BRAIN.md` и `docs/VAULT.md`.

### Бонус: сколько это стоит — `jarvis usage`

```bash
jarvis usage                # сводка за 30 дней
jarvis usage --by-model      # разбивка по моделям/провайдерам
jarvis usage --by-platform   # CLI / Telegram / Discord / cron / API — что расходует больше
jarvis usage --by-day --json # для своих графиков/скриптов
```

Hermes уже пишет каждую сессию (модель, токены, стоимость) в `~/.hermes/state.db` — `jarvis usage`
просто читает эту базу **локально и только на чтение** (не трогает и не блокирует Hermes, даже пока он
работает) и печатает таблицу. Никакого облачного дашборда, прокси или отдельного логирования не
заводится — идея подсмотрена у open-source трекеров расходов LLM (TokenTelemetry, tokscale, llm.log,
TokenTracker — все делают то же самое: читают уже существующие данные, а не создают новые). Стоимость
`$0.00` обычно значит локальную модель через Ollama или провайдера, который не публикует цену для Hermes.

## 4. HUD-панель «Модель ИИ» — переключение одной кнопкой

Панель **«Модель ИИ»** на HUD (`hud/static/index.html`, эндпоинты `GET/POST /api/model` →
`hud/model_switch.py`) показывает и позволяет менять сразу семь независимых полей, не открывая
терминал и не редактируя `config.yaml` руками:

| Поле в панели | Ключ `config.yaml` | Что определяет |
|---|---|---|
| Чат | `model.default` | основная модель разговора |
| Зрение | `auxiliary.vision.model` | распознавание скриншотов/фото |
| Сжатие истории | `auxiliary.compression.model` | сжатие длинного диалога |
| Заголовки сессий | `auxiliary.title_generation.model` | автозаголовки в истории чатов |
| Картинки: провайдер | `image_gen.provider` | `nous\|fal\|openai\|xai\|krea\|openrouter\|meta-ai\|openai-compatible` |
| Картинки: модель | `image_gen.model` | конкретная модель генерации изображений |
| Озвучка: провайдер | `tts.provider` | движок синтеза речи |

Каждое поле сохраняется отдельным вызовом `hermes config set <ключ> <значение>` (как и
`jarvis ollama use`) — редактируется только то поле, которое реально изменили, остальные не
трогаются. Это тот же принцип «модель под задачу, а не одна на всё», что уже был у Hermes для
`auxiliary.vision` — просто вынесенный в один экран вместо семи разных мест.

### Профили провайдеров — быстрое переключение между несколькими ключами (Round 12)

Hermes уже умеет держать сразу несколько настроенных провайдеров одновременно и переключаться
между ними (`hermes model`/`/model`, см. [AI Providers](https://hermes-agent.nousresearch.com/docs/integrations/providers))
— но каждый раз вручную вводить 2-4 значения (`model.provider`, `model.default`, ключ) неудобно.
Панель «Модель ИИ» ниже основных полей показывает блок **«Профили провайдеров»**:

- **Сохранить текущее как профиль** — под именем (например `openrouter` или `дом-ollama`)
  запоминается набор значений: `model.provider`/`model.default`/`model.base_url` и, по желанию,
  один API-ключ (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
  `XAI_API_KEY`, `GROQ_API_KEY`, `DEEPSEEK_API_KEY`, `FIREWORKS_API_KEY`).
- **▶ Применить** — одной кнопкой прогоняет `hermes config set` для каждого сохранённого поля
  профиля — переключение занимает секунду вместо ручного ввода всех значений заново.
- **✕ Удалить** — убрать сохранённый профиль.

Хранится в `$HERMES_HOME/jarvis/model_profiles.json` (права доступа ограничены владельцу,
как у файла сессии Telegram) — эндпоинты `GET/POST /api/model/profiles`,
`POST /api/model/profiles/apply`, `POST /api/model/profiles/delete` (`scripts/model_switch.py`).
API-ключи в списке профилей в HUD показываются замаскированными (`…1234`) — полное значение
уходит только в сам `hermes config set` при применении профиля, не остаётся в браузере лишний раз.

## Сводка: что где настраивается

| Что | Команда/меню | Где хранится |
|---|---|---|
| Провайдер + ключ + модель чата | `hermes model` / трей «ИИ: ключи / модель / провайдер…» / HUD «Модель ИИ» | `~/.hermes/config.yaml` (`model.*`), `~/.hermes/.env` |
| Модель для зрения | `jarvis ollama use <модель> --vision` (локально) или ручная правка `config.yaml` / трей «ИИ: модель для зрения…» / HUD «Модель ИИ» | `~/.hermes/config.yaml` (`auxiliary.vision.*`) |
| Модель для картинок/озвучки | HUD «Модель ИИ» | `~/.hermes/config.yaml` (`image_gen.*`, `tts.provider`) |
| Локальная модель (офлайн, без ключа) | `jarvis ollama pull/use` | Ollama (`~/.ollama/models`) + `~/.hermes/config.yaml` |
| Отправить файл/фото/голосовое в мессенджер | `jarvis_send_message(action=send_file)` / `jarvis_voice_note` / HUD «🎙️» | `hermes send "MEDIA:<путь>"` |
| Календарь | `jarvis calendar setup` | см. [docs/CALENDAR.md](CALENDAR.md) |
