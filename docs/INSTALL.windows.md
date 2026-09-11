# Установка J.A.R.V.I.S. на Windows

Полноценный порт: те же возможности, что на macOS (голос, HUD, база знаний BRAIN, хранилище файлов VAULT,
управление системой, мессенджеры), кроме нескольких вещей, у которых в Windows просто нет публичного API
(см. таблицу «Отличия от macOS» ниже). Работает **нативно**, без WSL — только PowerShell 5.1+ и Python.

## 0. Что понадобится

| | Минимум | Рекомендуется |
|---|---|---|
| Windows | 10 (21H2+) x86_64 | 11, x86_64 или ARM64 |
| PowerShell | 5.1 (предустановлен) | 7+ (`winget install Microsoft.PowerShell`) |
| ОЗУ | 8 ГБ | 16 ГБ (локальный Whisper `small` + Ollama) |
| Диск | 3 ГБ | 10 ГБ (если Ollama-модели) |
| LLM | ключ OpenRouter / Anthropic / OpenAI / Gemini **или** Ollama | OpenRouter (доступ к 300+ моделям одним ключом) |

> Полностью офлайн-вариант: Ollama (`qwen3:8b` / `llama3.1`) + локальный Whisper + системный голос SAPI (`win_say`).
> Тогда единственное, что уходит в сеть, — погода (wttr.in) и то, что вы явно попросите найти.

Права администратора **не нужны** — всё ставится в профиль текущего пользователя
(`%LOCALAPPDATA%\hermes`), автозапуск регистрируется в Планировщике заданий без повышения прав.

## 1. Скачать проект

Скачайте zip последнего релиза с GitHub (или `git clone https://github.com/Ayazbog11/hermes-jarvis-all.git`),
распакуйте, откройте PowerShell в этой папке (Shift + правый клик в Проводнике → «Открыть окно PowerShell здесь»).

> Windows Defender/антивирус может на несколько секунд задержать первый запуск установщика, пока сканирует —
> это нормально. Если бандл Hermes ставит `uv.exe` и антивирус помечает его ложноположительно, добавьте
> исключение: `Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\hermes\bin"`.

## 2. Разрешить выполнение скриптов (один раз)

По умолчанию Windows блокирует запуск непонятно откуда скачанных `.ps1`. Разрешите для текущего пользователя:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 3. Запустить установщик

```powershell
./install.ps1
```

Что произойдёт (каждый шаг печатается на экран):

1. **Проверка системы** — Windows 10/11, PowerShell 5.1+.
2. **winget-пакеты** — `ffmpeg` (для скриншотов/камеры/аудио пайплайна). `-NoExtraTools` — пропустить.
3. **Hermes Agent** — официальный установщик Nous Research (`install.ps1`, без прав администратора, `%LOCALAPPDATA%\hermes`, добавляет `bin` в PATH пользователя, портативный Git). Если Hermes уже стоит — шаг пропускается.
4. **Голос** — `faster-whisper`, `edge-tts`, `sounddevice`, `numpy`, `openwakeword` в venv Hermes. Модель Whisper скачается при первом использовании (~460 МБ для `small`). `-NoVoice` — пропустить.
5. **Трей-приложение** — `pystray`, `pillow`. `-NoApp` — пропустить.
6. **Плагины** — копируются в `%LOCALAPPDATA%\hermes\plugins\jarvis-core`, `jarvis-windows`, `jarvis-brain`.
7. **Личность и навыки** — `SOUL.md` (ваш прежний сохраняется в `.bak`), `skills\jarvis\*`, `hooks\jarvis-boot`, `BOOT.md`, HUD в `jarvis\hud`, трей-приложение в `jarvis\tray`.
8. **Конфиг** — `config/config.jarvis.windows.yaml` **вливается** в `config.yaml`: ваши существующие значения не перезаписываются, списки плагинов/toolsets объединяются. Бэкап: `config.yaml.bak.jarvis`.
9. **API-сервер** — в `.env` добавляются `API_SERVER_ENABLED=true` и случайный `API_SERVER_KEY` (нужны HUD).
10. **Команда `jarvis`** — `%LOCALAPPDATA%\hermes\bin\jarvis.ps1` + `jarvis.cmd` (можно набирать просто `jarvis`), путь добавляется в PATH пользователя.
11. **Планировщик заданий** (спросит) — автозапуск HUD и gateway при входе в систему, аналог launchd на macOS (см. `scripts/setup_scheduled_tasks.py`).
12. **Трей-приложение запускается** — значок статуса рядом с часами.
13. **cron** (спросит) — брифинг 08:00, вечерний итог 21:00, ночная ревизия базы знаний 03:30, чистка памяти по воскресеньям, heartbeat каждые 3 часа (`JARVIS_HEARTBEAT=0` — не создавать).
14. **Модель** — если не настроена, откроется `hermes model`.
15. **doctor.py** — диагностика.

Флаги: `-Yes` (без вопросов), `-NoScheduledTask`, `-NoVoice`, `-NoExtraTools`, `-NoCron`, `-NoApp`, `-HermesHome <путь>`.

Если Hermes у вас живёт не в `%LOCALAPPDATA%\hermes` — передайте `-HermesHome ...` или задайте `$env:HERMES_HOME`
перед запуском: установщик и команда `jarvis` будут использовать его автоматически.

## 4. Права и настройка Windows

```powershell
jarvis perms      # откроет нужные разделы «Параметры Windows»
```

| Раздел | Зачем |
|---|---|
| **Микрофон** (Параметры → Конфиденциальность → Микрофон) | wake word, push-to-talk |
| **Уведомления** | `win_notify`, тосты об обновлениях |
| **Тихий час / Focus Assist** | Windows не даёт публичного API для чтения/переключения — переключается вручную (`ms-settings:quiethours`), `win_focus` честно об этом сообщает |
| **Веб-камера** | `win_camera_snap` (опционально, нужен ffmpeg) |
| **Outlook** | для `win_calendar` и `win_contacts` — должен быть установлен и настроен профиль по умолчанию (JARVIS обращается к нему через COM, не через облачный Graph API) |

Если запускаете через Планировщик заданий (gateway/HUD в фоне) — им отдельные разрешения обычно не нужны,
но если что-то не работает именно в фоне (а из интерактивного PowerShell работает) — см. `docs/TROUBLESHOOTING.md`.

## 5. Выбор LLM-провайдера

```powershell
hermes model              # интерактивный выбор
# или напрямую:
hermes config set OPENROUTER_API_KEY sk-or-...
hermes config set model anthropic/claude-sonnet-4
```

Те же рекомендации, что на macOS — см. `docs/USAGE.md`. Для Ollama на Windows: `hermes model` → Custom endpoint
`http://localhost:11434/v1`.

## 6. Первый запуск

```powershell
jarvis
```

В TUI:
```
/voice on          включить голос (микрофон + TTS)
/wake on           слушать «Hey Jarvis» в фоне
/brief             брифинг
```
Скажите: *«Hey Jarvis, открой Блокнот и сделай громкость тридцать»*.

HUD:
```powershell
jarvis hud         # запустит сервер и откроет http://127.0.0.1:8765
```

Значок в трее: правый клик → то же самое меню, что открывает `jarvis app open`.

## 7. Мессенджеры (опционально)

```powershell
hermes gateway setup       # мастер: Telegram / Discord / WhatsApp / Slack / Email
jarvis gateway             # запустить
```
Работает идентично macOS-версии — Hermes gateway кроссплатформенный.

## 8. Голос: тонкая настройка

`%LOCALAPPDATA%\hermes\config.yaml` (или `hermes config set ...`):

```yaml
stt:
  local: {model: small, language: ru}
tts:
  provider: edge          # облачный, бесплатный, без ключа
  sapi:                   # офлайн-резерв: System.Speech.Synthesis (голоса из Windows)
    voice: "Microsoft Irina Desktop"
```

`win_say` — озвучить текст голосом SAPI напрямую (не через основной TTS Hermes) или остановить речь.

## 9. Отличия от macOS

| Возможность | macOS | Windows | Комментарий |
|---|---|---|---|
| Управление приложениями/окнами/громкостью/яркостью/Wi-Fi/BT | ✅ `mac_*` | ✅ `win_*` | 1:1 |
| Скриншоты, буфер обмена, набор текста, хоткеи | ✅ | ✅ | 1:1 |
| Календарь/контакты | ✅ Calendar.app/Contacts.app (Automation) | ✅ Outlook (COM), если установлен | На Windows без Outlook вернёт понятную ошибку вместо краша |
| Заметки | ✅ Notes.app | ✅ файлы `.md` в `jarvis\notes` | Проще, но кроссплатформенно |
| Focus/Не беспокоить | ✅ get+set через `defaults`/shortcuts | ⚠️ только заглушка `get`; `set` — нет публичного API | Задокументированное ограничение Windows, не баг |
| Скрипты-автоматизации | ✅ Shortcuts.app (Siri) | ✅ `.ps1`/`.bat` через `win_shortcut` + ярлыки на Рабочем столе/SendTo | `jarvis shortcuts` генерирует их |
| Автозапуск | ✅ launchd | ✅ Планировщик заданий (`schtasks`), без прав администратора | `scripts/setup_scheduled_tasks.py` |
| Трей/строка меню | ✅ JARVIS.app (Swift) | ✅ `jarvis_tray.pyw` (Python + pystray) | Тот же набор пунктов меню |
| TTS офлайн | ✅ `say` | ✅ SAPI (`System.Speech.Synthesis`) | Плюс общий edge-tts (облачный, бесплатный) на обеих ОС |
| Хранилище VAULT, база знаний BRAIN, wake word, STT, gateway, cron | ✅ | ✅ | Полностью общий кроссплатформенный код Hermes/jarvis-core/jarvis-brain |

## 10. Диагностика

```powershell
jarvis selftest [-fix]     # проверка всех win_* инструментов на этой машине, без LLM
jarvis doctor [-fix]       # модель, плагины, API, HUD, автозапуск, права, хранилище
```

См. также `docs/TROUBLESHOOTING.md` (общий) и раздел Windows там же.
