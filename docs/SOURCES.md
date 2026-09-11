# Источники: что было прочитано и что из этого взято

Краткий, «ссылочный» список всех сайтов, статей и репозиториев, изученных при создании проекта.
Подробный разбор идей — в [RESEARCH.md](RESEARCH.md); здесь — только адрес → что взято.
Код ни из одного стороннего проекта не копировался: заимствованы идеи, форматы и приёмы.

## 1. Hermes Agent — ядро, на котором всё построено

| Источник | Что взято |
|---|---|
| https://github.com/NousResearch/hermes-agent | Сам агент (MIT). `install.sh` ставит его официальным скриптом; JARVIS — набор плагинов, навыков и конфигов поверх него |
| https://hermes-agent.nousresearch.com/docs/getting-started/installation | Пути `~/.hermes/…`, `~/.local/bin/hermes`, требования (Python 3.11, uv) |
| https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins | Формат `plugin.yaml` + `register(ctx)`, `register_tool/hook/command`, хранилище `plugin_data_dir` |
| https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks (+ raw `website/docs/user-guide/features/hooks.md`) | Таблица хуков и их сигнатуры: `pre_llm_call` → `{"context":…}` (контекст хода без порчи prompt-cache), `post_tool_call` (журнал сбоев), `pre_transcription` → `{"prompt":…}` (словарь для Whisper), `transform_llm_output` (полировка голосового ответа) |
| https://hermes-agent.nousresearch.com/docs/user-guide/features/tts, …/voice | Ключи `voice/stt/tts/wake_word` в конфиге, `brew install portaudio ffmpeg…`, `/voice on` |
| https://hermes-agent.nousresearch.com/docs/user-guide/features/skills | Frontmatter `SKILL.md`, `skill-bundles/*.yaml`, готовые навыки `apple-notes/reminders/imessage/findmy` |
| https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server | OpenAI-совместимый сервер `:8642` (`API_SERVER_KEY`) — через него HUD говорит с агентом |
| https://hermes-agent.nousresearch.com/docs/user-guide/features/cron, …/gateway | `hermes cron create "every day at 08:00" …`, gateway-хуки (`gateway:startup` → BOOT.md), `/heartbeat` |
| https://hermes-agent.nousresearch.com/docs/user-guide/configuration | Приоритет CLI > config.yaml > .env, `${VAR}`, `approvals.mode: smart` → merge-стратегия `scripts/merge_config.py` |

## 2. Готовые «Джарвисы» и управление Mac

| Источник | Что взято |
|---|---|
| https://github.com/eadmin2/jarvis_ai | HUD как отдельный лёгкий сервер с SSE-лентой действий агента; разговор с Hermes через API :8642; launchd-автозапуск; cinematic boot |
| https://github.com/nixfred/MacOS_Mark-XXXV | osascript/System Events как универсальный канал к macOS; список разрешений (Accessibility, Automation, Screen Recording) → `jarvis perms`, `jarvis selftest` |
| YouTube «Self-Hosted JARVIS» https://www.youtube.com/watch?v=dOeFE4fBrEg | Локальная LLM (Ollama), wake word без облака, приватность как фича → офлайн-профиль в INSTALL.md |
| Десятки «Jarvis на Python» (speech_recognition + pyttsx3) на GitHub/YouTube | Список фраз-намерений, которых пользователи ожидают (открой/закрой, громкость, «что на экране», таймеры, брифинг) → покрыты инструментами `mac_*` и навыком `mac-control`. Их архитектура (регулярки, свой цикл распознавания) — сознательно **не** взята |
| https://github.com/legnoh/focus-cli, gist https://gist.github.com/drewkerr/0f2b61ce34e2b9e3ce0ec6a92ab05c18, https://github.com/Macjutsu/super/discussions/237 | Как прочитать активный режим Focus macOS без публичного API: `~/Library/DoNotDisturb/DB/Assertions.json` + `ModeConfigurations.json` (нужен Full Disk Access) → `Watchdog.macos_focus()`, `mac_focus` |

## 3. Память агентов (база знаний `jarvis-brain`)

| Источник | Что взято |
|---|---|
| https://github.com/vectorize-io/hindsight и https://hindsight.vectorize.io/blog/2026/03/04/mcp-agent-memory | Три операции retain/recall/**reflect**; «ментальные модели» — живые резюме сущностей; разделение фактов и выводимых наблюдений → `brain_reflect`, `stale_entity_summaries`/`entity_summary`, `kind=insight` |
| https://ai.miraheze.org/wiki/Hindsight | Схема recall: семантика + BM25 + граф + временной фильтр параллельно, затем rerank → у нас FTS5 + карточки + дневник, rerank отложен до schema v3 |
| Graphiti / Zep — https://github.com/getzep/graphiti, обзоры https://evermind.ai/blog и https://www.cognee.ai/blog (сравнения фреймворков памяти 2026) | Темпоральный граф: факт имеет `valid_at/invalid_at`, при изменении закрывается, а не удаляется → `valid_from/valid_until/superseded_by`, `supersede()`, `brain_history` |
| Mem0 — https://github.com/mem0ai/mem0 (через те же обзоры) | Entity linking при записи; дедупликация на входе → `_auto_link()`, Jaccard-дедуп 0.75 и `possible_conflicts`. Отдельный LLM-вызов на каждую запись — **не** взят (дорого в голосовом диалоге) |
| Letta / MemGPT — https://github.com/letta-ai/letta | «Агент сам управляет своей памятью» → ночная ревизия по явным правилам навыка, операции `merge/archive/rekind/kind_rename` |
| Generative Agents (Park et al., 2023) — https://arxiv.org/abs/2304.03442 | Reflection: из потока наблюдений периодически выводятся обобщения → шаг «рефлексия» в ночной ревизии (0–2 insight за ночь) |
| https://www.vellum.ai/blog (агентная память и проактивные reach-outs) | Проактивные обращения с дедупликацией → heartbeat + запись предупреждений в базу |
| ReMe (file-first markdown memory) — через обзор cognee.ai | Человекочитаемый снимок памяти → `BRAIN.md`/`PROFILE.md`, экспортируемые ночью |

## 4. Проактивность

| Источник | Что взято |
|---|---|
| https://docs.openclaw.ai/gateway/heartbeat (+ гайд на skywork.ai) | Периодический тик читает `HEARTBEAT.md`, отвечает `NO_REPLY`, если сказать нечего, помнит прошлые предупреждения → навык `jarvis/heartbeat`, файл `config/HEARTBEAT.md`, cron каждые 45 мин |

## 5. macOS-специфика и безопасность

| Источник | Что взято |
|---|---|
| Apple Support — «Controlling app access to files in macOS», документация `osascript`, `shortcuts run`, `pmset`, `mdfind`, `screencapture` | Поведение утилит, на которых построены `mac_*` инструменты; какие права нужны каждому |
| OWASP — CSRF Prevention Cheat Sheet | Same-origin проверка и JSON-only POST на HUD (без CORS `*`) |

## 6. Раунд 4 — сравнение с другими open-source ассистентами, безопасность CI, Google Calendar

| Источник | Что взято |
|---|---|
| https://github.com/isair/jarvis | Прямая интеграция с Ollama HTTP API одной командой (list/pull/use) вместо ручного `hermes model` → `jarvis ollama` |
| https://github.com/bertrandmbanwi/Jarvis | Идея явного Ollama-фолбэка рядом с облачными моделями — уже покрыта `auxiliary.vision`/`model.provider: custom`, добавлен только удобный CLI поверх |
| https://github.com/rezaulhreza/jarvis | Подтверждение Ollama-first подхода как распространённого паттерна для локальной модели в 2026 |
| https://github.com/alex2772/kuni | Рассмотрен для идей Telegram-интеграции — архитектурно другая задача (tdlib userbot + RAG-компаньон), не применимо напрямую |
| https://developers.google.com/identity/protocols/oauth2/native-app | OAuth "Desktop app" loopback-redirect + PKCE — основа `plugins/jarvis-core/gcalendar.py` |
| oneuptime.com/blog (Security Scanning with GitHub Actions), microsoft/secrets-detection, GitHub Community Discussions #168683 | gitleaks (secret scanning, `fetch-depth: 0`) + `pip-audit` (dependency scanning) + Dependabot для версий GitHub Actions → `.github/workflows/security.yml`, `.github/dependabot.yml`, `.gitleaks.toml` |
| https://github.com/ollama/ollama/blob/main/docs/api.md | HTTP API Ollama (`/api/tags`, `/api/pull`) — основа `scripts/ollama_local.py` без внешних зависимостей |
| https://polyformproject.org/licenses/noncommercial/1.0.0 | Уже использован как база `LICENSE` (см. предыдущий раунд) |

## 7. Раунд 5 — Obsidian, гибридный поиск (BM25 + эмбеддинги), обзор ~100 second-brain проектов

| Источник | Что взято |
|---|---|
| https://github.com/isair/jarvis | Embedding-based поиск памяти через локальный `nomic-embed-text` (Ollama) с graceful fallback на keyword search — прямой прообраз `plugins/jarvis-brain/embeddings.py` |
| https://github.com/coleam00/second-brain-starter | «70% вектор + 30% ключевые слова» и «Memory Search (hybrid RAG)» как явный архитектурный паттерн — подтверждение выбора гибрида, а не одного из двух |
| https://github.com/smixs/agent-second-brain, https://github.com/flepied/second-brain-agent | Obsidian как стандартное хранилище second-brain проектов (plain Markdown + вики-ссылки + daily notes) — обоснование для `vault_manage obsidian_note` |
| https://help.obsidian.md (How Obsidian stores data), форум Obsidian | Точные пути `obsidian.json` на Windows (`%APPDATA%\obsidian`) и Linux (`~/.config/obsidian`, snap/flatpak) — раньше искалось только на macOS |
| Документация Daily notes (obsidianmd-obsidian-help.mintlify.app) | Формат `.obsidian/daily-notes.json` (`folder`, `format` — Moment.js-токены) — основа `_daily_notes_settings`/`_moment_like_date` |
| https://mljourney.com (Ollama REST API Reference), webscraft.org | Формат запроса/ответа `/api/embed` (`{"model", "input"}` → `{"embeddings": [[...]]}`) — основа `embeddings.py:embed()` |
| ai-tldr.dev (sqlite-vec explained), theconsensus.dev | Сравнение sqlite-vec/C-расширений vs чистый Python: для личного хранилища (не веб-масштаб) линейный перебор без доп. зависимостей — обоснованный выбор, не сделано ради простоты |
| Reciprocal Rank Fusion (стандарт Elasticsearch/OpenSearch `reciprocal_rank_fusion`) | Формула `score = Σ 1/(k+rank+1)`, k=60 — способ объединить BM25-score и cosine-similarity без калибровки весов |

## Что сознательно не взято и почему

- **Полноценные векторные БД** (Qdrant, Milvus, Chroma, mem0/Cognee как внешний сервис): для личной базы в тысячи заметок/файлов чистый Python + BLOB в существующей `brain.db` не уступает по скорости и не требует лишнего процесса — ломало бы принцип «скачал и запустил». Лёгкая версия семантического поиска реализована локально в Раунде 5 (`plugins/jarvis-brain/embeddings.py`, опционально, требует только Ollama, которая уже была нужна проекту).
- **Свой агентский цикл / STT / TTS**: всё это есть в Hermes и работает одинаково в терминале, Telegram и Discord.
- **Регулярки «фраза → действие»** из классических Jarvis: выбор инструмента делает модель по JSON-схемам.
- **Полная замена локального STT/TTS-стека** (Moonshine ONNX, Kokoro и т.п. из isair/jarvis, bertrandmbanwi/Jarvis): Hermes уже даёт faster-whisper/openWakeWord/Edge-TTS кросс-платформенно из коробки — дублирование не оправдано (см. `docs/RESEARCH.md`, Раунд 3 и 4).
