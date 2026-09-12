# Исследование: откуда взяты идеи

Перед проектированием были изучены документация Hermes Agent и популярные open-source
«Джарвисы» (GitHub, YouTube). Ниже — что и почему заимствовано.

## Hermes Agent (NousResearch/hermes-agent) — основа

Что уже есть «из коробки» и что мы **не** переписывали:
- агентский цикл с tool calling, любые провайдеры LLM, prompt caching;
- **голосовой режим**: wake word (openWakeWord `hey_jarvis` ✔, Porcupine, sherpa open-vocabulary с русским), локальный faster-whisper, TTS Edge/ElevenLabs/OpenAI/Piper, барж-ин, стоп-фразы;
- память (MEMORY.md/USER.md, Honcho), самообучающиеся навыки (`skills/`), FTS-поиск сессий;
- 40+ инструментов: терминал, файлы, браузер (Playwright), поиск, vision, image gen, TTS, todo, делегирование субагентам;
- gateway: Telegram, Discord (+ голосовые каналы), WhatsApp, Slack, Signal, iMessage, Email, Matrix, Mattermost… + OpenAI-совместимый API-сервер;
- cron с доставкой в чат, `/heartbeat`, hooks (`gateway:startup` → BOOT.md), MCP-клиент, computer-use;
- готовые навыки для macOS: `apple-notes`, `apple-reminders`, `imessage`, `findmy`, `obsidian`;
- плагины: `plugin.yaml` + `register(ctx)`; хуки `pre_llm_call` (возвращает `{"context": ...}`), `pre/post_tool_call`, `on_stream_delta` и др.

Ключевые уроки из документации, применённые в коде:
- **SOUL.md — слот #1 системного промпта**, отдельный от `system_prompt` в конфиге → личность JARVIS не ломает механику агента.
- **Контекст хода через `pre_llm_call`**, а не через системный промпт → prompt cache остаётся валидным.
- **BOOT.md через gateway-хук** — официальный паттерн для «проснулся → проверил всё → молчи, если [SILENT]».
- **Slash-команды** — Hermes отдаёт «сырой» текст; мы парсим `/timer 10 чай` сами.
- **Плагиновые хуки никогда не должны падать** — обёрнуты в try/except с логированием.
- **Merge, а не overwrite** конфига пользователя (`hermes config` уважает `${ENV}`; списки объединяем).

## eadmin2/jarvis_ai (GitHub) — HUD и «клиент к Hermes»

Проект «HUD + push-to-talk поверх Hermes на Mac». Заимствовано:
- идея **HUD как отдельного лёгкого сервера**, который получает события от агента и стримит в браузер (SSE);
- разговор с Hermes через **OpenAI-совместимый API :8642** (`API_SERVER_KEY`), а не через внутренние классы;
- **launchd**-автозапуск и cinematic boot sequence;
- **live tool feed** — видеть, что агент делает прямо сейчас (мы получили это дешевле — через хуки плагина, а не парсинг логов).

Отличие: их HUD — отдельное приложение с собственным STT/TTS (faster-whisper + ElevenLabs). Мы делегируем голос Hermes (единый конвейер и в TUI, и в Telegram), а в HUD оставили Web Speech API как лёгкий запасной вариант.

## nixfred/MacOS_Mark-XXXV — управление Mac

Голосовой контроль macOS через AppleScript. Заимствовано:
- **osascript как универсальный канал** к System Events, приложениям, уведомлениям;
- перечень необходимых **разрешений** (Accessibility, Automation, Screen Recording) и понимание, что их нужно просить заранее → `jarvis perms` и таблица в INSTALL.md;
- паттерн «фраза → инструмент» превращён у нас в **JSON-схемы для LLM** (модель сама выбирает инструмент — не нужны регулярки).

## Классические «Jarvis на Python» (YouTube, десятки репозиториев)

Типичный набор: `speech_recognition` + `pyttsx3` + `if 'открой' in query:`. Что взяли:
- **фразы-намерения**, на которые пользователи реально рассчитывают (открой/закрой, громкость, музыка, «что на экране», «который час», таймеры, напоминания, «расскажи анекдот») → покрыты инструментами и SKILL.md `mac-control`;
- ожидание **утреннего брифинга** «погода + календарь + новости» → навык `briefing` + cron;
- **режим тишины / ночной режим**.
Что сознательно **не** взяли: свои циклы распознавания, `webbrowser.open` вместо нормальной автоматизации, хардкод ключевых слов.

## Видео «Self-Hosted JARVIS» (YouTube, dOeFE4fBrEg) и подобные

Идеи: локальная LLM через Ollama, wake word без облака, приватность как фича, домашняя автоматизация. Отражено в INSTALL.md (офлайн-профиль) и навыке `home-automation` (Home Assistant toolset Hermes + HomeKit через Shortcuts).

## OpenClaw / OpenInterpreter / Open-Assistant-подобные проекты

Взято понимание «компьютер как инструмент агента»: computer-use, browser automation, делегирование. Всё это есть в Hermes (`hermes computer-use install`, `browser` toolset, `delegate_task`), мы лишь включили нужные toolsets в конфиг и описали в SOUL.md, когда их применять.

## Раунд 3 — исследование памяти агентов и проактивности (сентябрь 2026)

### Фреймворки памяти: Mem0, Graphiti/Zep, Letta, Cognee, ReMe, Hindsight
Обзоры (evermind.ai, cognee.ai, vellum.ai) сходятся на одном наборе идей, часть которых мы уже реализовали, часть — взяли теперь:

| Идея | Откуда | Что сделано в JARVIS |
|---|---|---|
| Факт — интервал времени, а не строка; при смене «закрывается», а не удаляется | **Graphiti / Zep** (temporal knowledge graph, `valid_at/invalid_at`) | `valid_from/valid_until/superseded_by`, `supersede()`, `brain_history`, схема v2 с миграцией |
| Entity linking при записи без вызова модели | **Mem0** | `_auto_link()` — заметка сама цепляется к карточке (с русскими словоформами) |
| «Ментальные модели» — живые документы про сущность, обновляемые по мере накопления памяти | **Hindsight** (Vectorize, MIT, github.com/vectorize-io/hindsight) | `stale_summaries()` в ночном плане + операция `entity_summary` |
| Три операции: retain / recall / **reflect** — синтез ответа из памяти, а не список результатов | **Hindsight** | `brain_reflect` собирает заметки+карточки+эпизоды+историю, синтез делает основная модель |
| Раздельные «наблюдения» (inferred, evolving) и «факты» | Hindsight, Cognee «memify» | у нас это `kind=insight` с confidence 0.6 + ночная рефлексия (было с v1.2) |
| Проактивные «reach-outs» с дедупликацией | Vellum, OpenClaw | heartbeat + журнал предупреждений в базе |

Что **не** взяли и почему: векторные БД/эмбеддинги (Mem0, Cognee) — для личной базы в тысячи заметок FTS5 + карточки
покрывают 90 % запросов, а лишний сервис ломает принцип «скачал и запустил»; отдельный LLM-вызов на каждую запись
(Mem0 extraction) — дорого и медленно в голосовом диалоге, у нас извлечение делает та же модель прямо в ходе.

### OpenClaw — heartbeat
docs.openclaw.ai/gateway/heartbeat: агент периодически (по умолчанию 30 мин) читает `HEARTBEAT.md`, выполняет проверки
в **основной** сессии (помнит, о чём уже предупреждал) и отвечает `NO_REPLY`, если сказать нечего. Перенесено как навык
`jarvis/heartbeat` + файл `~/.hermes/jarvis/HEARTBEAT.md` + cron каждые 45 минут; дедупликация — через эпизоды базы знаний.
Сравнение с нашим Watchdog: Watchdog — 0 LLM-вызовов для «механических» проверок, heartbeat — для проверок, требующих
суждения («есть ли к этой встрече незакрытые обещания?»).

### Определение Focus macOS без публичного API
Gist drewkerr + обсуждение в Macjutsu/super #155: состояние Focus лежит в `~/Library/DoNotDisturb/DB/Assertions.json`
(`storeAssertionRecords[].assertionDetails.assertionDetailsModeIdentifier`), имя режима — в `ModeConfigurations.json`.
Использовано в `Watchdog.macos_focus()` и `mac_focus get`. Установка режима публичного API тоже не имеет — через Shortcuts.

### Хуки Hermes (user-guide/features/hooks.md)
Подтверждены и задействованы `post_tool_call` (статус/ошибка каждого инструмента), `pre_transcription` (возвращает
`{"prompt": …}` — подсказка Whisper), `transform_llm_output` (замена финального ответа; первый непустой выигрывает).

## Раунд 4 — сплошной аудит инструментов и сравнение с другими open-source «Jarvis» (сентябрь 2026)

### Сравнение с другими open-source ассистентами на GitHub
Изучены (2026): `isair/jarvis` (полностью локальный, Ollama по умолчанию, Moonshine ONNX + faster-whisper
фолбэк, Piper/Chatterbox TTS, offline-диктовка по хоткею), `bertrandmbanwi/Jarvis` (macOS, 3-уровневая
маршрутизация моделей Fast/Brain/Deep + Ollama-фолбэк, Kokoro TTS, OpenWakeWord), `rezaulhreza/jarvis`
(Ollama-first, 35+ инструментов, веб-UI). Общий вывод: голосовой стек (faster-whisper/openWakeWord/Edge-TTS)
у нас не хуже — эти проекты выигрывают только там, где **явно связывают Ollama с остальной системой одной
командой**, а не оставляют это на усмотрение `hermes model`. Взято точечно: **`jarvis ollama` —
CLI-обёртка над Ollama HTTP API** (список/скачивание/выбор модели одной командой, включая отдельно модель
для зрения), а не просто инструкция «откройте hermes model и введите адрес». Полный локальный STT-стек
(Moonshine/whisper.cpp) сознательно не взят — Hermes уже даёт faster-whisper из коробки на всех трёх ОС
через единый `stt.provider: local`, дублировать не нужно.

### Supply-chain безопасность CI (2026 best practice)
Обзоры (oneuptime.com/blog, GitHub Community Discussions, microsoft/secrets-detection) сходятся на
минимальном наборе для публичного репозитория: **secret scanning** (gitleaks/TruffleHog, полная история
через `fetch-depth: 0`) и **dependency scanning** (`pip-audit` для Python, Dependabot для версий самих
GitHub Actions — нередкий вектор атаки на CI через компрометацию сторонних actions). Добавлено:
`.github/workflows/security.yml` (gitleaks + pip-audit, push/PR + еженедельно по расписанию),
`.github/dependabot.yml` (обновления `github-actions` еженедельно), `.gitleaks.toml` (allowlist для
намеренно фиктивных токенов в тестах/документации — не ослабляет реальное сканирование).

### Что не взято и почему
- Полная замена STT/TTS/wake-word стека — уже лучший вариант для этого проекта (см. Раунд 3), заново
  проверено против 2026-обзоров: faster-whisper и openWakeWord остаются рекомендуемым выбором.
- `alex2772/kuni` (tdlib-userbot с RAG-памятью) — архитектурно другая задача (Telegram-компаньон через
  личный аккаунт), не «джарвис»-ассистент через Bot API; не применимо напрямую.

## Раунд 5 — Obsidian, гибридный поиск и обзор ≈100 open-source «Джарвисов»/second-brain проектов (сентябрь 2026)

Просмотрены (GitHub topics/поиск, релизы, README): `isair/jarvis` (100% локальный, embedding-based tool
routing, knowledge-graph память, `nomic-embed-text` через Ollama как эмбеддинг-бэкенд — с graceful fallback
на keyword search, если у чат-провайдера нет embeddings endpoint), `bertrandmbanwi/Jarvis`, `vannu07/jarvis`,
`fedcal/open-jarvis` (мульти-девайсная инфраструктура, mem0/Qdrant/Zep для памяти — оверинжиниринг для личного
ассистента одного пользователя), `coleam00/second-brain-starter` (архитектурный blueprint: «70% вектор + 30%
ключевые слова = лучшее из обоих», FastEmbed локально), `smixs/agent-second-brain` (Telegram → Obsidian vault,
knowledge-graph память под названием autograph), `flepied/second-brain-agent` (markdown+Obsidian → ChromaDB →
LangChain RAG), `AgriciDaniel/claude-obsidian`, `swarmclawai/swarmvault` и ещё около 80 репозиториев по темам
`personal-knowledge-management`, `second-brain`, `hybrid-rag`, `ai-second-brain` — плюс сравнительные обзоры
RAG-фреймворков (`docs/RESEARCH.md`-класса статьи firecrawl.dev/vellum.ai/evermind.ai за 2026 год).

**Общий вывод, встречающийся почти везде**: чистый BM25/keyword-поиск (то, что у JARVIS было с версии 1.8)
не находит перефразировки, а полноценный внешний vector DB (Qdrant/Milvus/Chroma) — избыточная инфраструктура
для одного пользователя и одной SQLite-базы. Победивший паттерн (isair/jarvis, coleam00/second-brain-starter,
LightRAG/txtai/AnythingLLM) — **гибрид: BM25 + локальные эмбеддинги, объединённые через Reciprocal Rank
Fusion** (тот же алгоритм по умолчанию в Elasticsearch/OpenSearch). Взято точечно и реализовано в
`plugins/jarvis-brain/embeddings.py`: эмбеддинги — через уже интегрированную в этом проекте Ollama
(`nomic-embed-text`, ~270 МБ, тот же паттерн, что у isair/jarvis), векторы хранятся как обычный BLOB в
`brain.db` (не sqlite-vec/faiss/numpy — обзор `sqlite-vec` подтвердил, что для десятков тысяч кусков линейный
перебор чистым Python сравним по скорости и не тянет C-расширение, которое не всегда собирается на всех
платформах Windows/Linux). Полностью опционально — без Ollama всё работает как раньше (чистый BM25).

**Obsidian**: у `smixs/agent-second-brain`, `flepied/second-brain-agent`, `AgriciDaniel/claude-obsidian` и
десятков других second-brain проектов Obsidian — стандартный формат хранения (plain Markdown + YAML
frontmatter + `.obsidian/daily-notes.json` для дневных заметок). У нас Obsidian уже подключался как источник
для индексации (`vault connect notes-obsidian`), но поиск vault-а работал только на macOS, а запись — голым
текстом без конвенций Obsidian. Исправлено: поиск `obsidian.json` теперь работает на Windows (`%APPDATA%`),
Linux (`~/.config`, snap, flatpak) и macOS; добавлена запись заметок **по конвенциям Obsidian**
(YAML-frontmatter, поддержка дневных заметок по личным настройкам daily-notes.json пользователя) — см.
`vault_manage obsidian_note`/`jarvis vault note` в `docs/VAULT.md`.

**Что не взято и почему**: knowledge-graph память (autograph, mem0-стиль граф связей) — у jarvis-brain уже
есть облегчённая версия того же самого (`entities`/`relations` таблицы, карточки, `brain_entity relate`),
полноценный граф с decay/health-scoring избыточен для личного ассистента и добавил бы сложность без
пропорциональной пользы; multi-device/AR-инфраструктура (`fedcal/open-jarvis`) — вне рамок проекта (Windows/
macOS/Linux десктоп, не носимые устройства).

## Раунд 6 — обзор ≥50 проектов уровня Hermes-Jarvis/Jarvis/агент, локальный учёт расходов (сентябрь 2026)

По запросу «просмотри не менее 50 гитхаб-проектов уровня Hermes-Jarvis/Jarvis/агент и добавь себе функции,
обнови свои функции» просмотрены (GitHub topics/списки/README): `awesome-agent-orchestrators` (список
паттернов оркестрации агентов, включая `model-watchdog` — авто-откат конфигурации при отказе, без
зависимостей), несколько версий `awesome-ai-agents-2026`, локальные трекеры стоимости/токенов LLM —
`VasiHemanth/tokentelemetry`, `junhoyeo/tokscale`, `lanesket/llm.log`, `he-yufeng/TokenTracker`,
`inferock-bench`, и собственная документация Hermes Agent (session-storage / `state.db` схема,
встроенная команда `hermes usage`, слэш-команды `/usage` и `/insights`), `0xNyk/awesome-hermes-agent`
(список skills/плагинов сообщества — ничего напрямую переиспользуемого не найдено), OWASP Top 10 for
Agentic Applications, паттерны self-healing/circuit-breaker — всего свыше 50 источников.

**Общий вывод**: у почти всех локальных «трекеров расходов LLM» (TokenTelemetry, tokscale, llm.log,
TokenTracker) один и тот же принцип — **не создавать новую телеметрию, а читать то, что уже пишется**
(логи, прокси-трафик, локальную БД). Аудит собственного репозитория (`grep` по `scripts/`, `plugins/`,
`bin/`) показал: JARVIS не имел вообще никакой видимости расходов, хотя Hermes Agent уже пишет каждую
сессию (модель, `input_tokens`/`output_tokens`/`estimated_cost_usd`, платформа-источник) в
`~/.hermes/state.db`. Реализовано точечно и в том же духе, что и остальные инструменты этого проекта
(без внешних зависимостей, без прокси/подмены сети): **`jarvis usage`** (`scripts/usage_report.py`) —
открывает `state.db` в режиме **только для чтения** (SQLite URI `mode=ro`, безопасно даже пока Hermes
работает), агрегирует по модели/платформе/дню и печатает текстовую таблицу или JSON. Устойчив к разным
версиям схемы Hermes (проверяет наличие колонок через `PRAGMA table_info` перед запросом — старые базы
без `estimated_cost_usd` просто покажут `$0.00`, а не упадут с ошибкой).

**Рассмотрено, но отложено в этом раунде**: авто-откат конфигурации по образцу `model-watchdog` для
`jarvis ollama use` (снимок `config.yaml` перед сменой модели → пинг новой модели → авто-откат при
неудаче) — полезная идея на будущее (в `scripts/ollama_local.py:cmd_use()` на момент этого раунда нет
проверки, что новая модель действительно отвечает), не реализована здесь, чтобы не размывать фокус между
двумя разнородными фичами. **Реализовано в следующем же раунде** — см. Раунд 7 (`cmd_use`/`ping_model`/
`_restore_snapshot` в `scripts/ollama_local.py`, коммит `81b956f`, Feature #6): снимок затрагиваемых ключей
`config.yaml` перед записью, один пинг новой модели через `hermes chat -q`, автоматический откат на
снятые значения при неудаче (кроме `--vision`/`--no-verify`, где пинг пропущен осознанно).

**Что не взято и почему**: обёртывание/дублирование встроенной `hermes usage` — решено читать `state.db`
напрямую (тот же паттерн, что уже используют `vault.py`/`embeddings.py`: прямой SQLite/HTTP без
подпроцессов), это даёт полный контроль над форматом вывода и не зависит от того, установлена ли у
пользователя версия Hermes с этой командой; полноценный веб-дашборд/график — противоречит собственному
принципу проекта «не трогать HUD/веб, всё новое — в CLI».

## Раунд 7 — отправка файлов/голосовых, выбор модели из HUD, рабочая память и метрики по образцу `alex2772/kuni` (сентябрь 2026)

По прямому запросу пользователя разобран репозиторий `alex2772/kuni` (C++20 tdlib-userbot, RAG-дневник,
sleep-consolidation, Stable Diffusion/Whisper/OmniVoice через docker-compose, транспарентный
OpenAI-совместимый прокси, Prometheus/Grafana) на предмет того, что из его *возможностей* (не архитектуры —
Kuni написан на C++ вокруг личного Telegram-аккаунта через tdlib, JARVIS остаётся Python-плагином поверх
Hermes Agent) применимо здесь. Перенесено четыре идеи:

1. **Отправка файлов/фото/голосовых по команде** — у Kuni это встроено в её Telegram-клиент (фото из SD,
   голос из OmniVoice отправляются в чат как обычные вложения). Здесь: `messenger.send_file()` (обёртка
   над `hermes send "MEDIA:<путь>"`, тот же принцип «не писать свой HTTP-клиент», что и у текстовой
   отправки) + `jarvis_send_message(action=send_file)`.
2. **Голосовые сообщения** — у Kuni это OmniVoice (self-hosted клон голоса через Docker). Полноценный
   голосовой клон — избыточно для личного ассистента и требует Docker/GPU-инфраструктуры, которой нет в
   базовой установке JARVIS; вместо этого переиспользован уже работающий каскад TTS самого HUD
   (`hud/tts.py`: edge-tts → `say`/SAPI/espeak-ng) через новый `voice_note.py` — тот же результат
   («озвучь и отправь») без второй инфраструктуры синтеза речи.
3. **Working memory / `<things_to_remember>`** — у Kuni отдельный markdown-файл (`data/working_memory.md`)
   для незавершённых задач на 1-3 дня, инъецируемый в промпт при каждой сессии и обновляемый при
   «дампе» контекста в дневник. Перенесено почти буквально: `plugins/jarvis-core/working_memory.py` +
   инструмент `jarvis_working_memory` (add/list/clear) + инъекция `render_context()` в
   `build_context()` рядом с `[JARVIS context]`. Осознанно **не** тронута постоянная база знаний
   (`jarvis-brain`) — working memory описывает буквально другой слой (дни, не месяцы) и не должна с ней
   смешиваться, как и в оригинале у Kuni working memory отделена от диалогового RAG-дневника.
4. **Метрики использования LLM (Prometheus)** — у Kuni свой C++-счётчик `llm_usage_*` по `model`/`chat`/
   `function`, экспортируемый на порту 9464 для Prometheus+Grafana. Здесь нет отдельного демона метрик —
   вместо этого HUD получил `GET /metrics` в стандартном текстовом формате Prometheus
   (`jarvis_llm_usage_input_tokens_total`/`..._output_tokens_total`/`..._cost_usd_total`/
   `jarvis_llm_sessions_total`, label `model`), переиспользующий тот же READ-ONLY код,
   что и `jarvis usage`/`/api/usage` (`scripts/usage_report.py:collect()`) — можно направить любой
   Prometheus-сервер на `http://<HUD>:8765/metrics` без установки Docker/Grafana-стека Kuni целиком.

Отдельно, тем же коммитом, закрыт хвост из Раунда 6: **безопасное переключение модели** для
`jarvis ollama use` по образцу `model-watchdog` (`awesome-agent-orchestrators`, см. Раунд 6) — снимок
затронутых ключей `config.yaml` перед записью, один пинг новой модели через `hermes chat -q`,
автоматический откат на снятые значения при неудаче (`scripts/ollama_local.py:cmd_use()`/`ping_model()`/
`_restore_snapshot()`); `--no-verify` отключает проверку, `--vision` пропускает её осознанно (текстовый
пинг не показателен для vision-модели).

**Что уникальной архитектуры Kuni сознательно не взято и почему**: (a) ~~диалог через личный
Telegram-аккаунт (tdlib userbot) — нарушает ToS Telegram~~ — **пересмотрено в Раунде 8, см. ниже**:
изначальная оценка смешивала два разных сценария. ToS Telegram запрещает автоматизацию, которая
имитирует человека для массовой рассылки незнакомым людям/накрутки чужих аккаунтов без их ведома —
но не запрещает владельцу аккаунта самому дать собственному инструменту доступ к собственной
переписке (то же самое делает Telegram Desktop). Портировано полностью, см. Раунд 8; (b) транспарентный
OpenAI-совместимый прокси-сервер — у Hermes Agent уже есть собственный API-сервер
(`API_SERVER_ENABLED`, порт 8642) с OpenAI-совместимым фасадом, второй прокси поверх него был
бы дублированием; (c) диск-based RAG-дневник со sleep-consolidation через embedding similarity —
у JARVIS уже есть архитектурно похожий, но более безопасный аналог (`jarvis-brain`: структурированная
SQLite-таблица + явная ночная ревизия по человекочитаемым правилам, а не свободная LLM-компрессия
дневника), переписывать его под свободную консолидацию Kuni означало бы потерять уже проверенные
гарантии «ничего не теряем» (см. `docs/BRAIN.md`); (d) Stable Diffusion через self-hosted Docker — Hermes
уже даёт генерацию картинок через `image_gen.provider` (см. новый раздел HUD «Модель ИИ» в
`docs/AI-MODELS.md`), это не требует поднимать собственный inference-сервер.

## Раунд 8 — Telegram userbot через MTProto (пересмотр Раунда 7, сентябрь 2026)

Пользователь прямо указал на ошибку в рассуждении Раунда 7: пункт «нарушает ToS Telegram» был
верным описанием риска *в общем* (автоматизация личного аккаунта под видом человека — типичный
вектор спама/накрутки, который Telegram действительно преследует), но неверно применённым к
конкретному запрошенному сценарию — **личный ассистент владельца, работающий с его же собственным
аккаунтом по его же явному согласию**. Это не отличается по сути от того, что делает официальный
клиент Telegram Desktop, когда пользователь сам открывает его на своём компьютере: тот же протокол,
тот же аккаунт, то же согласие. Различие между «бот рассылает спам от чужого имени» и «я разрешаю
своему ассистенту читать мою же почту» существенно и было ошибочно не разделено в первой версии
этого документа.

Реализовано на [Telethon](https://docs.telethon.dev/) — чистой Python-реализации MTProto (того же
протокола, что и tdlib у Kuni), без необходимости собирать C++-код tdlib на каждой из трёх ОС.
Функционально — тот же уровень доступа, что даёт tdlib-userbot Kuni: чтение диалогов и
непрочитанных, чтение текста/типа медиа входящих сообщений, скачивание медиа, отправка
текста/файлов/голосовых от имени владельца аккаунта. Подробности архитектуры, настройки и
приватности — `docs/TELEGRAM.md`; код — `plugins/jarvis-core/telegram_userbot.py` (по образцу
`gcalendar.py`: локальное хранение credentials/сессии с chmod 600, никакой сети кроме прямого
MTProto-канала к серверам Telegram), CLI — `scripts/telegram_cli.py` (`jarvis telegram
setup/status/unread/dialogs/logout`), инструмент модели — `jarvis_telegram`
(status/dialogs/unread/read/mark_read/send/send_file/download_media).

## Раунд 12 — действия с сообщениями Telegram по образцу Kuni, профили провайдеров, фоновое прослушивание HUD (сентябрь 2026)

Пользователь явно указал вернуться к `alex2772/kuni` и добрать оставшиеся возможности, а также
попросил два самостоятельных улучшения: быстрое переключение между несколькими API-ключами
провайдеров моделей и режим «слушать постоянно» в HUD (аналог голосового ассистента Тони Старка —
не нужно каждый раз нажимать кнопку). Три независимых изменения одним раундом:

1. **Действия с сообщениями Telegram** — Kuni (через tdlib) умеет ставить реакции
   (`addMessageReaction`), редактировать (`editMessageText`/`editMessageCaption` — есть даже
   отдельный фикс на U+FE0F variation selector и REACTION_INVALID), удалять, пересылать сообщения
   и показывать статус «печатает» перед отправкой (кэшированные `getUser`/`getChat`, задержка на
   время `chatStreaming`). Портировано на Telethon (тот же MTProto, см. Раунд 8): `react()`
   (снимает реакцию при пустом emoji, сообщает текстом при REACTION_INVALID вместо трейсбека),
   `edit_message()` (только свои сообщения — ограничение протокола, не JARVIS),
   `delete_message()` (revoke=True по умолчанию — «Удалить для всех»), `forward_message()`,
   `set_typing()` (чисто косметика). Не портировано: клонирование голоса через OmniVoice/Docker —
   решение не изменилось с Раунда 7 (уже используется каскад TTS самого HUD); хранение
   диалога/памяти в отдельном RAG-дневнике Kuni — по-прежнему архитектурно покрыто `jarvis-brain`.
2. **Профили провайдеров моделей** (не заимствовано у Kuni — Kuni всегда работает с одним
   выбранным провайдером через `config.toml`; это отдельный самостоятельный запрос пользователя) —
   Hermes уже умеет держать несколько сконфигурированных провайдеров и переключаться командой
   `/model`/`hermes model`, но каждое переключение требует помнить/вводить провайдера, модель и
   ключ заново. `scripts/model_switch.py` добавляет именованные наборы этих значений
   (`model_profiles.json`, права только владельцу) с применением одной кнопкой в HUD.
3. **Фоновое прослушивание в HUD** — офлайн `wake_word` (openWakeWord) уже есть в голосовом TUI
   Hermes, но HUD — отдельная браузерная страница без доступа к нему. Добавлен браузерный аналог:
   continuous-режим Web Speech API с поиском имени ассистента в потоке слов и явным
   вкл/выкл-переключателем (кнопка + клавиша `W`) — сознательно НЕ включается автоматически при
   каждой загрузке страницы (браузеры всё равно требуют новый жест пользователя для микрофона после
   перезагрузки вкладки), только по явному действию пользователя, как и обещано.

## Что уникального добавлено в этом проекте

1. Плагин `jarvis-macos` — 29 типизированных инструментов с единым форматом ошибок и подсказками по разрешениям.
2. Ситуационный контекст `[JARVIS context]` (время, батарея, активное окно, режим, таймеры) на каждом ходе.
3. Режимы `focus/night/presentation`, влияющие и на поведение модели, и на систему (через Shortcuts).
4. Таймеры/будильники, переживающие рестарт.
5. HUD без зависимостей с панелями `text/markdown/image/video/web/chart`, которые агент открывает сам через инструмент.
6. Один установщик, который вливается в существующую установку Hermes, не ломая её.
7. Самообслуживаемая база знаний (`jarvis-brain`): структурированная память с таксономией, карточками и связями,
   релевантный контекст на каждом ходе, дневник по дням и ночная реструктуризация агентом по явным правилам —
   идея заимствована из подходов MemGPT/Letta («агент управляет своей памятью») и Generative Agents («reflection»),
   реализована на SQLite+FTS5 без внешних сервисов.
8. Темпоральная память, журнал сбоев инструментов (агент ночью учится на собственных ошибках), словарь имён для STT,
   справка из базы перед встречей, синхронизация с Focus macOS, `jarvis selftest` — проверка всех интеграций без LLM.
