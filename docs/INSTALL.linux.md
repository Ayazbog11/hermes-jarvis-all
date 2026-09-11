# Установка J.A.R.V.I.S. на Linux

Полноценный порт: те же возможности, что на macOS/Windows (голос, HUD, база знаний BRAIN, хранилище файлов
VAULT, управление системой, мессенджеры), реализованные через стандартные утилиты рабочего стола Linux
(wmctrl/xdotool, pactl/amixer, nmcli, bluetoothctl, upower, grim/scrot, xclip/wl-clipboard, notify-send,
espeak-ng…) вместо AppleScript/PowerShell. Работает **нативно**, без контейнеров/WSL — обычный Python
3.10+ и bash.

Linux — не единая платформа: набор рабочих столов (GNOME/KDE/XFCE/Sway/…) и протоколов (X11/Wayland) влияет
на то, что вообще возможно на конкретной машине. `jarvis selftest` честно показывает, чего не хватает именно
на вашей системе, и не притворяется, что всё работает одинаково везде.

## 0. Что понадобится

| | Минимум | Рекомендуется |
|---|---|---|
| Дистрибутив | любой современный (Ubuntu/Debian/Fedora/Arch/openSUSE/Alpine) | Ubuntu/Fedora с GNOME или KDE |
| Python | 3.10+ | 3.11/3.12 |
| ОЗУ | 8 ГБ | 16 ГБ (локальный Whisper `small` + Ollama) |
| Диск | 3 ГБ | 10 ГБ (если модели Ollama) |
| LLM | ключ OpenRouter / Anthropic / OpenAI / Gemini **или** Ollama | OpenRouter (доступ к 300+ моделям одним ключом) |

> Полностью офлайн-вариант: Ollama (`qwen3:8b` / `llama3.1`) + локальный Whisper + `espeak-ng` (офлайн TTS,
> `linux_say`). Тогда единственное, что уходит в сеть, — погода (wttr.in) и то, что вы явно попросите найти.

Прав root **не требуется** для установки самого JARVIS/Hermes (всё ставится в `~/.hermes` и `~/.local/bin`) —
root нужен только `sudo` пакетному менеджеру, чтобы поставить системные утилиты (шаг 1 ниже, можно пропустить
и доставить вручную позже).

## 1. Скачать проект

Самый быстрый способ — одна команда (скачивает и сразу запускает установщик, шаги 1–2 сразу):

```bash
curl -fsSL https://raw.githubusercontent.com/Ayazbog11/hermes-jarvis-all/main/get.linux.sh | bash
```

Или вручную:

```bash
git clone https://github.com/Ayazbog11/hermes-jarvis-all.git
cd hermes-jarvis-all
```

Или скачайте zip последнего релиза с GitHub и распакуйте.

## 2. Запустить установщик

```bash
bash install.linux.sh
```

Что произойдёт (каждый шаг печатается на экран):

1. **Определение дистрибутива и пакетного менеджера** — apt/dnf/yum/pacman/zypper/apk.
2. **Системные утилиты** (best-effort, спросит подтверждение) — `portaudio`, `ffmpeg`, `wmctrl`, `xdotool`,
   `xclip`/`wl-clipboard`, `playerctl`, `brightnessctl`, `libnotify-bin`, `scrot`/`grim`, `upower`, `bluez`,
   `NetworkManager`, `espeak-ng`. `--no-system-packages` — пропустить (доставите вручную по подсказкам
   `jarvis selftest`).
3. **Hermes Agent** — официальный установщик Nous Research (`~/.hermes`, добавляет `bin` в PATH пользователя
   через `~/.local/bin`). Если Hermes уже стоит — шаг пропускается.
4. **Голос** — `faster-whisper`, `edge-tts`, `sounddevice`, `numpy`, `openwakeword` в venv Hermes. Модель
   Whisper скачается при первом использовании (~460 МБ для `small`). `--no-voice` — пропустить.
5. **Плагины** — копируются в `~/.hermes/plugins/jarvis-core`, `jarvis-linux`, `jarvis-brain`.
6. **Личность и навыки** — `SOUL.md` (ваш прежний сохраняется в `.bak`), `skills/jarvis/*`, `hooks/jarvis-boot`,
   `BOOT.md`, HUD в `jarvis/hud`, трей-приложение в `jarvis/tray`.
7. **Конфиг** — `config/config.jarvis.linux.yaml` **вливается** в `config.yaml`: ваши существующие значения
   не перезаписываются, списки плагинов/toolsets объединяются. Бэкап: `config.yaml.bak.jarvis`.
8. **API-сервер** — в `.env` добавляются `API_SERVER_ENABLED=true` и случайный `API_SERVER_KEY` (нужны HUD).
9. **Команда `jarvis`** — `~/.local/bin/jarvis` (bash), путь уже в PATH после установки Hermes.
10. **systemd --user юниты** (спросит) — автозапуск HUD и gateway при входе в систему, аналог launchd на macOS
    (`jarvis-hud.service`, `jarvis-gateway.service`, `jarvis-updater.service`+`.timer`). Также включает
    `loginctl enable-linger`, чтобы юниты стартовали даже без графической сессии (headless/сервер).
    `--no-systemd-user` — пропустить.
11. **Трей-приложение** (спросит, если есть `$DISPLAY`/`$WAYLAND_DISPLAY`) — `pystray`+`pillow`, автозапуск
    через `~/.config/autostart/jarvis-tray.desktop`. На GNOME для видимости иконки в трее нужно расширение
    **AppIndicator and KStatusNotifierItem Support** (extensions.gnome.org) — без него значка не будет видно,
    но сам JARVIS продолжит работать (HUD/gateway не зависят от трея).
12. **cron** (спросит) — брифинг 08:00, вечерний итог 21:00, ночная ревизия базы знаний 03:30, чистка памяти
    по воскресеньям, heartbeat каждые 3 часа (`JARVIS_HEARTBEAT=0` — не создавать). `--no-cron` — пропустить.
13. **Модель** — если не настроена, откроется `hermes model`.
14. **doctor.py** — диагностика.

Флаги: `--yes`, `--no-systemd-user`, `--no-voice`, `--no-system-packages`, `--no-cron`, `--hermes-home=DIR`.

Если Hermes у вас живёт не в `~/.hermes` — задайте `HERMES_HOME=...` перед запуском: установщик и команда
`jarvis` будут использовать его автоматически.

## 3. Права и системные утилиты

У Linux нет единого центра разрешений вроде macOS — большинство ограничений сводятся к отсутствующим
консольным утилитам:

```bash
jarvis perms       # список утилит X11/Wayland/общих для проверки
jarvis selftest --fix   # прогонит каждый linux_* инструмент и покажет, чего не хватает именно у вас
```

| Категория | Нужны | Зачем |
|---|---|---|
| Окна/набор текста (X11) | `wmctrl`, `xdotool` | `linux_window`, `linux_type`, активация приложений |
| Скриншоты | `grim`+`slurp` (Wayland) или `scrot`/`gnome-screenshot`/`spectacle` (X11) | `linux_screenshot` |
| Буфер обмена | `xclip` (X11) или `wl-clipboard` (Wayland) | `linux_clipboard` |
| Звук | `pactl` (PipeWire/PulseAudio) или `amixer` | `linux_volume` |
| Яркость | `brightnessctl` | `linux_brightness` (не на всех ноутбуках есть стандартный backlight) |
| Wi-Fi | `nmcli` (NetworkManager) | `linux_wifi` |
| Bluetooth | `bluetoothctl` (BlueZ) | `linux_bluetooth` |
| Батарея | `upower` (или sysfs как фолбэк) | `linux_battery` |
| Медиа | `playerctl` (MPRIS) | `linux_media` — работает с любым плеером, поддерживающим MPRIS |
| Уведомления | `notify-send` (libnotify) | `linux_notify` |
| Офлайн-голос | `espeak-ng` | `linux_say` (фолбэк, если edge-tts недоступен) |
| Тёмная тема / «Не беспокоить» | GNOME (`gsettings`) | `linux_dark_mode`, `linux_focus` — на других DE ограничено |
| Календарь | `khal` (опционально, CalDAV) | `linux_calendar` — без него доступны только локальные напоминания |

## 4. Выбор LLM-провайдера

```bash
hermes model              # интерактивный выбор
# или напрямую:
hermes config set OPENROUTER_API_KEY sk-or-...
hermes config set model anthropic/claude-sonnet-4
```

Те же рекомендации, что на macOS/Windows — см. `docs/USAGE.md`. Для Ollama: `hermes model` → Custom endpoint
`http://localhost:11434/v1`.

## 5. Первый запуск

```bash
jarvis
```

В TUI:
```
/voice on          включить голос (микрофон + TTS)
/wake on           слушать «Hey Jarvis» в фоне
/brief             брифинг
```
Скажите: *«Hey Jarvis, открой Firefox и сделай громкость тридцать»*.

HUD:
```bash
jarvis hud         # запустит сервер и откроет http://127.0.0.1:8765
```

Трей: значок в системном лотке (или верхней панели на GNOME с расширением AppIndicator) — то же меню, что
открывает `jarvis app open`.

## 6. Мессенджеры (опционально)

```bash
hermes gateway setup       # мастер: Telegram / Discord / WhatsApp / Slack / Email
jarvis gateway             # запустить
```
Работает идентично macOS/Windows-версии — Hermes gateway кроссплатформенный.

## 7. Голос: тонкая настройка

`~/.hermes/config.yaml` (или `hermes config set ...`):

```yaml
stt:
  local: {model: small, language: ru}
tts:
  provider: edge          # облачный, бесплатный, без ключа
  espeak:                 # офлайн-резерв: espeak-ng
    voice: "ru"
```

`linux_say` — озвучить текст голосом espeak-ng напрямую (не через основной TTS Hermes) или остановить речь.

## 8. Отличия от macOS/Windows

| Возможность | macOS | Windows | Linux | Комментарий |
|---|---|---|---|---|
| Приложения/окна/громкость/яркость/Wi-Fi/BT | ✅ `mac_*` | ✅ `win_*` | ✅ `linux_*` | На Linux зависит от установленных утилит (см. таблицу выше) |
| Скриншоты, буфер обмена, набор текста, хоткеи | ✅ | ✅ | ✅ | На Wayland часть операций (произвольные хоткеи) ограничена без `ydotool` |
| Календарь/контакты | ✅ Calendar.app/Contacts.app | ✅ Outlook (COM) | ⚠️ только `khal`, если настроен | Без CalDAV-клиента доступны только локальные напоминания |
| Заметки | ✅ Notes.app | ✅ файлы `.md` | ✅ файлы `.md` | Кроссплатформенно |
| Focus/«Не беспокоить» | ✅ get+set | ⚠️ только заглушка `get` | ✅ get+set только на GNOME (`gsettings`) | На KDE/XFCE — ограничение, инструмент честно об этом сообщает |
| Автозапуск | ✅ launchd | ✅ Планировщик заданий | ✅ systemd --user | `config/systemd/*.service` |
| Трей/строка меню | ✅ JARVIS.app (Swift) | ✅ `jarvis_tray.pyw` (Python+pystray) | ✅ `jarvis_tray.py` (Python+pystray) | На GNOME нужно расширение AppIndicator |
| TTS офлайн | ✅ `say` | ✅ SAPI | ✅ `espeak-ng` | Плюс общий edge-tts (облачный, бесплатный) на всех трёх |
| Удаление файлов | ✅ Корзина | ✅ Корзина (`send2trash`/VisualBasic) | ✅ freedesktop Корзина (`gio trash`/`trash-put`) | Никогда безвозвратно |
| Хранилище VAULT, база знаний BRAIN, wake word, STT, gateway, cron | ✅ | ✅ | ✅ | Полностью общий кроссплатформенный код Hermes/jarvis-core/jarvis-brain |

## 9. Диагностика

```bash
jarvis selftest [--fix]    # проверка всех linux_* инструментов на этой машине, без LLM
jarvis doctor [--fix]      # модель, плагины, API, HUD, systemd --user, права/утилиты, хранилище
```

См. также `docs/TROUBLESHOOTING.md` (общий) и раздел Linux там же.
