# Диагностика и решение проблем

Первое, что стоит запустить при любой проблеме:
```bash
jarvis doctor --fix      # 10 проверок (модель отвечает? плагины, API, gateway, HUD, launchd, права, хранилище, версия) + автопочинка
jarvis doctor --quick    # то же без ping модели и selftest прав (2 секунды)
jarvis status            # что запущено
hermes logs --follow     # живой лог агента (ошибки плагинов тоже здесь)
jarvis hud log           # лог HUD
```

## Что чинит `doctor --fix` сам
- нет `API_SERVER_ENABLED`/`API_SERVER_KEY` в `.env` → допишет (затем `jarvis gateway restart && jarvis hud restart`);
- плагины не включены → `hermes plugins enable …`; gateway/HUD не запущены → запустит; launchd-агенты выгружены → загрузит;
- папки `~/JARVIS` нет → создаст; нет прав macOS → откроет нужные панели (`selftest --fix`).
Что НЕ чинит: неверный ключ провайдера/пустой баланс (покажет ответ модели и предложит `hermes model`), права — их выдаёте вы.

## Установка

| Симптом | Причина / решение |
|---|---|
| `xcode-select: note: install requested` и скрипт вышел | Дождитесь установки Command Line Tools, запустите `./install.sh` снова |
| `brew: command not found` после установки Homebrew | Apple Silicon: `eval "$(/opt/homebrew/bin/brew shellenv)"`, затем повторить |
| `hermes: command not found` | `export PATH="$HOME/.local/bin:$PATH"`, откройте новый терминал; проверьте `~/.zshrc` |
| `uv pip install ".[voice,wake]"` падает на `pyaudio` | `brew install portaudio` и повторить: `cd ~/.hermes/hermes-agent && uv pip install -e ".[voice,wake]"` |
| Установщик просит `python3` | `brew install python@3.12` — нужен для HUD и merge_config (Hermes использует свой venv) |
| Плагины не видны в `/plugins` | `hermes config get plugins.enabled` должно содержать оба; `hermes plugins doctor ~/.hermes/plugins/jarvis-macos` |

## Голос

| Симптом | Решение |
|---|---|
| `/voice on` → «no audio device» / тишина | Микрофон разрешён для терминала? Системные настройки → Конфиденциальность → Микрофон. Перезапустите терминал |
| Wake word не срабатывает | `/wake status`; снизьте `wake_word.sensitivity` до 0.4; произносите «хей джАрвис» слитно; проверьте, что установлен `[wake]` extra |
| Ложные срабатывания | `wake_word.sensitivity: 0.7–0.8` |
| Распознаёт по-английски | `stt.local.language: ru` (или уберите — автоопределение) |
| Медленное распознавание | Модель `small` → `base`; на Intel Mac — `tiny`. Или облако: `stt.provider: groq` + `GROQ_API_KEY` (очень быстро) |
| Нет голоса в ответ | `tts.provider: edge` требует интернет. Офлайн: `tts.provider: piper` или `kittentts`. Проверить: `/tts тест` |
| Голос «робот»/не русский | `tts.edge.voice: ru-RU-DmitryNeural` (список: `edge-tts --list-voices`) |
| JARVIS перебивает сам себя | Используйте наушники или включите `voice.barge_in: false` |
| «Стоп» не останавливает | Стоп-фразы в `voice.stop_phrases` — добавьте свои |

## Управление Mac

| Симптом | Решение |
|---|---|
| `osascript is not allowed assistive access` / `-1719` | Универсальный доступ → добавьте терминал (и `python3`, если через launchd). После добавления перезапустите терминал |
| `Not authorized to send Apple events to Calendar` (`-1743`) | Конфиденциальность → Автоматизация → Terminal → включите Calendar/Reminders/Notes/Music/System Events. Если пункта нет — вызовите действие ещё раз, macOS покажет диалог |
| Скриншот чёрный/пустой | Запись экрана → добавьте терминал |
| `mac_bluetooth`: blueutil not found | `brew install blueutil` |
| `mac_camera_snap` не работает | `brew install imagesnap` + разрешение Камера |
| Яркость не меняется | `brew install brightness`; на внешних мониторах не поддерживается |
| Shortcuts не запускаются | Имя должно совпадать точно; проверьте `shortcuts list` |
| «Активное приложение» не определяется | Нужен Универсальный доступ для System Events |
| Действие выполнилось, но JARVIS говорит «не удалось» | Смотрите `hermes logs` — часто это таймаут osascript при первом запросе разрешения. Повторите |

## HUD

| Симптом | Решение |
|---|---|
| `jarvis hud` — порт занят | `lsof -i :8765`; `jarvis hud stop`; либо `JARVIS_HUD_PORT=8770 jarvis hud` (и `hud_url` в `plugins.entries.jarvis-core/jarvis-brain/jarvis-macos.settings`) |
| HUD пишет «Модель вернула пустой ответ» | Провайдер ответил без текста (часто у нестандартных прокси-моделей). `hermes model` → выберите рабочую модель; проверьте `hermes chat -q привет` в терминале |
| Открылся, но лента пустая | Плагин `jarvis-core` не загружен или `hud_url` не совпадает. Проверьте `/plugins` и `curl localhost:8765/api/status` |
| Чат в HUD: «Hermes API недоступен» | Запустите `jarvis gateway`; в `~/.hermes/.env` должен быть `API_SERVER_ENABLED=true` и `API_SERVER_KEY`; `curl localhost:8642/health` |
| 401 из API | Ключ в `.env` изменился после запуска HUD — `jarvis hud restart` |
| Видео на панели не играет | YouTube-embed требует интернет; локальные mp4 — только из белого списка папок (`~/Desktop`, `~/Downloads`, `~/Pictures`, `~/.hermes`) |
| Голос в HUD не работает | Web Speech API есть в Safari/Chrome, нет в Firefox; нужен `https` или `localhost` |

## База знаний (jarvis-brain)

| Симптом | Решение |
|---|---|
| `/brain stats` — «0 заметок», хотя просили запомнить | Проверьте `/plugins` (jarvis-brain включён?) и `hermes logs` на ошибки `jarvis-brain`. Модель должна вызывать `brain_remember`; страховка auto_capture ловит только фразы, начинающиеся с «запомни/запиши» |
| Контекст `[JARVIS memory]` не появляется | `min_score` слишком высок (снизьте до 0.8) или в запросе нет общих слов с заметками — используйте `brain_recall` явно |
| Ночная ревизия не идёт | Она выполняется процессом gateway (`hermes cron list`); gateway должен быть запущен ночью (launchd). Запустить вручную: `jarvis brain review` |
| «database is locked» | Одновременная запись из двух процессов при VACUUM — редко и само проходит (WAL). Если стабильно — `jarvis gateway stop`, повторить |
| Ревизия что-то сломала | `jarvis brain log 50` — увидеть изменения; откат из `brain.bak-*.db` (см. docs/BRAIN.md) |
| Нет FTS5 в python-sqlite | Плагин деградирует до LIKE-поиска (`stats.fts=false`); `brew install python@3.12` даёт SQLite с FTS5 |

## Gateway / мессенджеры

| Симптом | Решение |
|---|---|
| Бот не отвечает | `hermes gateway status`; `~/.hermes/logs/jarvis-gateway.log`; в `.env` — `TELEGRAM_BOT_TOKEN`; ваш user id в `allowed_users` (`hermes gateway setup`) |
| Голосовые в Telegram не распознаются | Нужен `ffmpeg` (`brew install ffmpeg`) и рабочий STT |
| BOOT.md не выполняется | Хук `~/.hermes/hooks/jarvis-boot` на месте? Логи: строки `jarvis-boot` в gateway.log |
| Cron не срабатывает | Cron исполняется процессом gateway — он должен быть запущен (launchd). `hermes cron list` |

## LLM

| Симптом | Решение |
|---|---|
| JARVIS повторяет одно и то же / говорит дважды | Ответ шёл на HUD двумя путями (плагин + прокси чата) и модель вызывала `mac_say` поверх TTS Hermes. С 1.6.1 дубли режутся на сервере, `mac_say` только по явной просьбе. Если повторы остались — это модель: `hermes model` → выберите другую |
| Не остановить речь | `jarvis hush` (или `Esc` в HUD, «Замолчать» в меню ◉, голосом «стоп»). Hermes TTS: барж-ин — просто начните говорить; `voice.stop_phrases` в config.yaml |
| «No API key» | `hermes model` или `hermes config set OPENROUTER_API_KEY …` |
| Модель не вызывает инструменты (только болтает) | Возьмите модель с хорошим tool-calling: Claude Sonnet, GPT-4.1, Gemini 2.5, Qwen3 ≥ 14b. Для Ollama проверьте, что модель поддерживает tools |
| Медленный первый ответ | Короче SOUL.md; меньше toolsets в `config.yaml`; провайдер с prompt caching (Anthropic) |
| Ответы на английском | В SOUL.md уже сказано отвечать на языке пользователя; добавьте `/personality` или явно «говори по-русски» — запомнится в памяти |

## Автозапуск (launchd)

```bash
launchctl list | grep ai.jarvis                      # статус
jarvis hud restart   /   jarvis gateway restart      # перезапуск (сами понимают, что сервис под launchd)
jarvis hud stop      /   jarvis gateway stop         # остановить до следующего входа в систему (агент выгружается, KeepAlive не поднимет его снова)
launchctl load -w ~/Library/LaunchAgents/ai.jarvis.hud.plist   # вернуть агент вручную раньше
tail -f "$HERMES_HOME"/logs/jarvis-hud.log             # (или ~/.hermes/logs/…)
```
Если после обновления macOS разрешения «слетели» — удалите терминал из списков и добавьте заново.

## Полный сброс JARVIS (без потери памяти Hermes)

```bash
./install.sh --yes --no-brew-tools --no-launchd    # переустановит плагины/скиллы/HUD/конфиг
rm ~/.hermes/plugin-data/jarvis-core/state.json    # сбросить режим и таймеры (или $HERMES_HOME/plugin-data/…)
```

## Куда смотреть в логах

| Лог | Что там |
|---|---|
| `~/.hermes/logs/agent.log` | ход агента, tool calls, ошибки плагинов (`plugins.jarvis-*`) |
| `~/.hermes/logs/jarvis-hud.log` | HTTP-запросы HUD, прокси к API |
| `~/.hermes/logs/jarvis-gateway.log` | gateway, cron, хуки |
| `hermes doctor` | окружение, ключи, зависимости |

## Приложение: Windows (нативный порт, без WSL)

Всё выше в этом файле относится к macOS-версии. Ниже — то, что отличается на Windows
(`plugins/jarvis-windows`, `install.ps1`, `bin/jarvis.ps1`).

Первым делом:
```powershell
jarvis doctor -fix        # то же самое, что на macOS, но проверяет Планировщик заданий вместо launchd
jarvis selftest -fix      # прогоняет все win_* инструменты
jarvis status
hermes logs --follow
jarvis hud log
```

### Установка

| Симптом | Причина / решение |
|---|---|
| `выполнение сценариев отключено в этой системе` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, затем повторить |
| `hermes: команда не найдена` после установки | Откройте новое окно PowerShell (PATH обновляется при установке пользовательской переменной, старые сессии его не видят) |
| Установщик виснет / Defender ругается на `uv.exe` | Ложное срабатывание антивируса: `Add-MpPreference -ExclusionPath "$env:LOCALAPPDATA\hermes\bin"` |
| `winget` не найден | Не критично — просто не поставится ffmpeg автоматически; поставьте вручную (https://ffmpeg.org) или через `-NoExtraTools` уберите предупреждение |
| Плагины не видны в `hermes plugins list` | `hermes plugins enable jarvis-core jarvis-windows jarvis-brain` |

### Голос

Та же логика STT/wake word/TTS, что на macOS (общий код Hermes). Отличия:
- офлайн TTS — не `say`, а SAPI (`System.Speech.Synthesis`); голоса ставятся через
  «Параметры → Время и язык → Речь» (или `Install-WindowsFeature`/языковые пакеты на Server);
- `win_say` — быстрый способ проверить, что SAPI вообще работает: `hermes chat -q "..."` не нужен;
- если микрофон не подхватывается — Параметры → Конфиденциальность и безопасность → Микрофон →
  разрешить классическим приложениям (не только UWP).

### Автозапуск (Планировщик заданий вместо launchd)

```powershell
schtasks /Query /FO LIST | Select-String "JARVIS-"           # статус
schtasks /End /TN "JARVIS-HUD"; schtasks /Run /TN "JARVIS-HUD"   # перезапуск (то же делает jarvis hud restart)
python "$env:LOCALAPPDATA\hermes\jarvis\setup_scheduled_tasks.py" status
python "$env:LOCALAPPDATA\hermes\jarvis\setup_scheduled_tasks.py" remove   # снять все задачи
Get-Content "$env:LOCALAPPDATA\hermes\logs\jarvis-hud.log" -Tail 60 -Wait
```
Задачи регистрируются на пользователя без прав администратора (`/RL LIMITED`, триггер «при входе»,
перезапуск при сбое как аналог launchd `KeepAlive`). Если после обновления Windows задачи пропали —
`install.ps1 -Yes` их пересоздаст.

### Focus Assist / «Не беспокоить»

Windows не даёт публичного API ни на чтение, ни на переключение этого режима из скрипта — `win_focus`
честно возвращает предупреждение вместо того, чтобы гадать по недокументированному реестру. Переключайте
вручную (значок в трее Windows или `ms-settings:quiethours`); `jarvis-core` следует общему состоянию
режима JARVIS независимо от реального Focus Assist ОС.

### Календарь (Google Calendar) не отвечает / needs_setup

Основной календарь JARVIS — Google Calendar (`jarvis_calendar`, кроссплатформенный) — см. подробную
настройку в `docs/CALENDAR.md`. Если инструмент возвращает `needs_setup: true`, выполните
`jarvis calendar setup` в терминале (один раз, откроет браузер для входа в Google). `jarvis calendar
status` покажет, настроен ли client и авторизован ли аккаунт.

### Telegram (личный аккаунт, MTProto) не отвечает / needs_setup

`jarvis_telegram` (userbot через Telethon/MTProto, не бот) — см. подробную настройку в
`docs/TELEGRAM.md`. Если инструмент возвращает `needs_setup: true`, выполните `jarvis telegram
setup` в терминале (один раз: `api_id`/`api_hash` с my.telegram.org, затем вход по номеру телефона
и коду). `jarvis telegram status` покажет, настроен ли и под каким аккаунтом авторизован. Если
`telethon не установлен` — `pip install telethon` (ставится автоматически установщиком).

### Outlook (fallback-календарь и контакты)

`win_calendar` (только как fallback — по умолчанию используется `jarvis_calendar`/Google) и
`win_contacts` идут через COM-объект `Outlook.Application` — Outlook должен быть установлен
и хоть раз открыт с настроенным профилем по умолчанию. Новый интерфейс «Outlook (new)»/веб-версия по COM
недоступны — нужен классический Outlook (Win32).

### Полный сброс JARVIS (без потери памяти Hermes)

```powershell
./install.ps1 -Yes -NoExtraTools -NoScheduledTask     # переустановит плагины/скиллы/HUD/конфиг
Remove-Item "$env:LOCALAPPDATA\hermes\plugin-data\jarvis-core\state.json"  # сбросить режим и таймеры
```

### Куда смотреть в логах

| Лог | Что там |
|---|---|
| `%LOCALAPPDATA%\hermes\logs\agent.log` | ход агента, tool calls, ошибки плагинов |
| `%LOCALAPPDATA%\hermes\logs\jarvis-hud.log` | HTTP-запросы HUD |
| `%LOCALAPPDATA%\hermes\logs\jarvis-gateway.log` | gateway, cron, хуки |
| Просмотр событий Windows → Журналы приложений и служб | не используется JARVIS напрямую, но полезно при сбоях Планировщика заданий |

## Приложение: Linux (нативный порт)

Всё выше в этом файле относится к macOS-версии. Ниже — то, что отличается на Linux
(`plugins/jarvis-linux`, `install.linux.sh`, `bin/jarvis` с ветками `IS_LINUX`).

Первым делом:
```bash
jarvis doctor --fix        # то же самое, что на macOS, но проверяет systemd --user вместо launchd
jarvis selftest --fix      # прогоняет все linux_* инструменты и покажет, каких утилит не хватает
jarvis status
hermes logs --follow
jarvis hud log
```

### Установка

| Симптом | Причина / решение |
|---|---|
| `bash: jarvis: команда не найдена` после установки | Откройте новый терминал (PATH обновляется при установке Hermes через `~/.local/bin`, старые сессии его не видят), либо `source ~/.bashrc` |
| Установщик не смог поставить системные пакеты | Разные дистрибутивы — разные названия пакетов; поставьте недостающее вручную по подсказке `jarvis selftest`, затем `--no-system-packages` при повторном запуске установщика |
| `sudo` попросил пароль и завис в неинтерактивном режиме | Запустите `bash install.linux.sh` из обычного терминала (не из cron/CI) либо `--no-system-packages` и доставьте зависимости заранее |
| Плагины не видны в `hermes plugins list` | `hermes plugins enable jarvis-core jarvis-linux jarvis-brain` |

### Голос

Та же логика STT/wake word/TTS, что на macOS (общий код Hermes). Отличия:
- офлайн TTS — не `say`, а `espeak-ng` (`sudo apt install espeak-ng`); голос заметно роботизированный,
  используется только как резерв, если edge-tts недоступен (нет сети/модуля);
- `linux_say` — быстрый способ проверить, что espeak-ng вообще работает;
- если микрофон не подхватывается — проверьте, что PipeWire/PulseAudio видит устройство
  (`pactl list sources short`), и что доступ к микрофону не заблокирован на уровне Flatpak/Snap,
  если Hermes запущен в песочнице.

### Автозапуск (systemd --user вместо launchd)

```bash
systemctl --user status jarvis-hud.service jarvis-gateway.service jarvis-updater.timer
systemctl --user restart jarvis-hud.service        # то же делает jarvis hud restart
journalctl --user -u jarvis-hud.service -f          # живой лог юнита
loginctl enable-linger "$USER"                      # если юниты не стартуют без графической сессии
```
Юниты лежат в `~/.config/systemd/user/*.service`. Если после обновления системы они пропали —
`bash install.linux.sh --yes` пересоздаст и включит их.

### Тёмная тема / «Не беспокоить»

`linux_dark_mode` и `linux_focus` работают только на GNOME (через `gsettings`) — на KDE/XFCE/других
окружениях они честно возвращают предупреждение об ограничении вместо того, чтобы делать вид, что
переключили что-то. `jarvis-core` следует общему состоянию режима JARVIS независимо от реального DND ОС.

### Wayland vs X11

Часть инструментов требует `xdotool`, которого на чистом Wayland-сеансе обычно нет:
`linux_type` (набор текста и хоткеи) и `linux_window` (left_half/right_half/center) в этом случае либо
используют `ydotool` (если установлен и запущен `ydotoold`), либо возвращают понятную ошибку.
Список окон/активация (`wmctrl`) при этом обычно работает и на Wayland через XWayland-совместимость.

### Трей-иконка не видна на GNOME

GNOME по умолчанию не показывает иконки в системном лотке — поставьте расширение
**AppIndicator and KStatusNotifierItem Support** через extensions.gnome.org или `gnome-extensions-app`.
HUD и gateway при этом продолжают работать независимо от видимости иконки трея.

### Полный сброс JARVIS (без потери памяти Hermes)

```bash
bash install.linux.sh --yes --no-system-packages   # переустановит плагины/скиллы/HUD/конфиг
rm -f ~/.hermes/plugin-data/jarvis-core/state.json  # сбросить режим и таймеры
```

### Куда смотреть в логах

| Лог | Что там |
|---|---|
| `~/.hermes/logs/agent.log` | ход агента, tool calls, ошибки плагинов |
| `~/.hermes/logs/jarvis-hud.log` | HTTP-запросы HUD |
| `~/.hermes/logs/jarvis-gateway.log` | gateway, cron, хуки |
| `journalctl --user -u jarvis-hud.service` / `jarvis-gateway.service` | если сервисы запущены через systemd --user |
