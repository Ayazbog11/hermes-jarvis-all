# JARVIS как приложение: JARVIS.app / трей-приложение и автообновление

С версии 1.4 JARVIS — не только команда в терминале, а обычное приложение со значком (в строке меню на
macOS, в системном трее на Windows и Linux), автозапуском и автообновлением с GitHub. Логика меню и
мастера первого запуска одинаковая на всех трёх платформах — различаются только технология значка
(Swift на macOS, Python+pystray на Windows/Linux) и то, как поднимаются фоновые сервисы (launchd /
Планировщик заданий / systemd --user).

## JARVIS.app (строка меню)

Собирается установщиком из одного Swift-файла (`app/JarvisMenuBar.swift`) — нужны только Xcode Command Line Tools,
никакого Xcode-проекта. В zip каждого релиза лежит готовая сборка `app/prebuilt/JARVIS.app.zip` (собирается в CI на macOS) —
если `swiftc` нет, установщик берёт её. Лежит в `~/Applications/JARVIS.app`, запускается при входе в систему (`ai.jarvis.app`).

Значок ◉ в строке меню — индикатор состояния:

| Цвет | Значение |
|---|---|
| голубой | HUD и API Hermes работают |
| жёлтый | что-то одно не отвечает |
| серый | сервисы остановлены |
| оранжевый | идёт обновление |
| `◉ ⬆` | доступно обновление |

Меню: открыть HUD (⌘H), голосовой чат в Terminal (⌘J), «Спросить…» (⌘A — ответ приходит уведомлением),
база знаний (⌘K), старт/стоп сервисов, брифинг, selftest, проверка обновлений (⌘U), откат, настройки (⌘,),
разрешения macOS, логи, GitHub.

**После запуска окна не появляется** — ищите ◉ справа вверху, рядом с часами. При первом запуске приложение проводит
**мастер настройки** (4 шага-окна): где искать значок → модель отвечает? (иначе откроет `hermes model`) → права macOS
(`selftest --fix`) → папка файлов `~/JARVIS` и HUD. Повторить: меню → «Мастер настройки…». Также в меню:
«Диагностика и починка» (⌘D, = `jarvis doctor --fix`) и «Папка файлов ~/JARVIS» (⌘F).
На MacBook с вырезом значки, которым не хватило места в строке меню, скрываются — закройте лишние или переставьте их, удерживая ⌘.
Диагностика: `jarvis app status` (запущен ли, есть ли crash-отчёт), `jarvis app debug` (запуск в терминале с выводом ошибок).

Приложение — только кнопки поверх команды `jarvis`; вся логика в скриптах, поэтому его можно пересобрать
в любой момент: `jarvis app build`.

## Трей-приложение (Windows, Linux)

`app-windows/jarvis_tray.pyw` и `app-linux/jarvis_tray.py` — тот же функционал на Python + pystray вместо
Swift: значок в системном трее, то же меню (HUD, голосовой чат в новом окне терминала, «Спросить…», база
знаний, старт/стоп сервисов, брифинг, selftest, обновления/откат, настройки, логи, GitHub), тот же мастер
первого запуска. Управление: `jarvis app open|quit|status` (на Windows и Linux нет отдельного `build` —
скрипт запускается напрямую интерпретатором Python venv Hermes).

- **Windows**: автозапуск через Планировщик заданий (задача `JARVIS-App`); уведомления — через PowerShell
  `NotifyIcon` (если pystray-иконка недоступна) или системные toast; открытие ссылок — `os.startfile`.
- **Linux**: автозапуск через `~/.config/autostart/jarvis-tray.desktop`; уведомления — `notify-send`;
  открытие ссылок — `xdg-open`. На GNOME для видимости самой иконки в верхней панели нужно расширение
  **AppIndicator and KStatusNotifierItem Support** — без него меню недоступно из трея, но HUD/gateway
  продолжают работать (открывайте `jarvis hud` вручную). Голосовой чат/брифинг/selftest/логи открываются в
  новом окне терминала — скрипт перебирает `x-terminal-emulator`/`gnome-terminal`/`konsole`/`xfce4-terminal`/
  `xterm`, берёт первый найденный.

## Автообновление

```
jarvis update                    проверить и установить (бэкап → скачивание → проверка → install.sh → перезапуск)
jarvis update --check            только проверить
jarvis update --status           версия, канал, режим, последняя проверка, есть ли откат
jarvis update --rollback         вернуть предыдущую установку
jarvis update --channel main     брать каждый коммит из main (по умолчанию stable — релизы GitHub)
jarvis update --auto auto        режим: off | check (по умолчанию: проверять и уведомлять) | auto (ставить самому)
jarvis update --hermes           обновить сам Hermes Agent
```

### Как это устроено

1. `~/.hermes/jarvis/install.json` (`%LOCALAPPDATA%\hermes\jarvis\install.json` на Windows) — что установлено
   (версия, коммит, репозиторий, канал, режим). Пишется установщиком соответствующей ОС.
2. Планировщик автозапуска раз в день (11:15) запускает `update.py auto`: `launchd`-агент `ai.jarvis.updater`
   на macOS, задача `JARVIS-Updater` в Планировщике на Windows, `jarvis-updater.timer` (systemd --user) на Linux:
   - `check` — сравнивает с GitHub (`releases/latest` для канала `stable`, `commits/main` для `main`); результат — в `update.json`;
   - в режиме `check` — системное уведомление (notification center / toast / notify-send) + событие на HUD + строка
     в контексте агента (JARVIS сам скажет «есть обновление», один раз);
   - в режиме `auto` — сразу установка.
3. Установка (`apply`):
   - скачивается tar.gz нужного коммита/релиза во временную папку;
   - **smoke-test**: все `.py` компилируются, установщик текущей ОС (`install.sh`/`install.ps1`/`install.linux.sh`)
     синтаксически корректен, файл `VERSION` есть;
   - **бэкап** всего, что трогает установщик (плагины, навыки, хук, HUD, SOUL.md, config.yaml) → `.../jarvis/backups/` (хранится 3);
   - тихий прогон установщика текущей ОС (`install.sh --yes --no-launchd --no-brew-tools --no-voice --no-cron --no-app`
     на macOS, `install.ps1 -Yes -NoScheduledTask -NoVoice -NoCron -NoApp` на Windows,
     `install.linux.sh --yes --no-systemd-user --no-system-packages --no-voice --no-cron` на Linux) — тот же код,
     что и при ручной установке;
   - если установщик упал или версия после установки старше — **автоматический откат**;
   - перезапуск HUD/gateway (launchd kickstart / Планировщик / `systemctl --user restart`), пересборка JARVIS.app
     при следующем `jarvis app build` (только macOS).
4. Голосом: «обнови себя» → инструмент `jarvis_update` (`status` → `apply confirmed=true`); «откати обновление» → `rollback`.

### Каналы и релизы

- `stable` — GitHub Releases. Релиз создаётся автоматически workflow'ом `.github/workflows/release.yml`,
  когда в `main` меняется файл `VERSION` (тесты должны пройти; заметки берутся из `docs/CHANGELOG.md`).
  Пока релизов нет, канал `stable` прозрачно берёт `main`.
- `main` — каждый коммит. Для разработчиков и нетерпеливых.

### Безопасность

- Скачивание только с `github.com`/`api.github.com` по HTTPS, репозиторий зафиксирован в `install.json`.
- Архив проверяется на path traversal, распаковка с `filter="data"`.
- Установщик никогда не трогает `.env`, базу знаний и память Hermes; `config.yaml` мерджится, а не перезаписывается, и есть в бэкапе.
- Ничего не устанавливается без прохождения smoke-test; любой сбой = откат.

### Выпуск новой версии (для вас как автора)

```bash
# внести изменения, обновить docs/CHANGELOG.md (раздел "## 1.5.0 — …")
echo 1.5.0 > VERSION
git commit -am "release 1.5.0" && git push
# → Actions: tests → release v1.5.0 → все установки на канале stable увидят обновление в течение суток
```
