# Календарь: Google Calendar (единый для macOS/Windows/Linux)

JARVIS использует Google Calendar как основной кроссплатформенный календарь — один и тот же код,
одна и та же настройка, работает одинаково на macOS, Windows и Linux. Инструмент модели —
`jarvis_calendar`; CLI для настройки и разовых проверок — `jarvis calendar`.

## Почему не Outlook и не «родной» календарь ОС

- **Outlook (COM)** — то, что было раньше на Windows: требует установленный и настроенный
  классический Microsoft Outlook. У многих его просто нет (Gmail/Google Workspace, встроенная
  «Почта», веб-Outlook без десктоп-клиента) — календарь у них просто не работал.
- **Windows.ApplicationModel.Appointments** (нативный календарь Windows) требует у вызывающего
  процесса *package identity* — то есть MSIX-упаковку приложения с сертификатом. Обычный `.py`/`.ps1`
  без отдельной сборки получает ошибку `0x80073D54: The process has no package identity` и не
  может даже открыть календарь. Упаковка всего JARVIS в MSIX — отдельный большой проект,
  непропорциональный пользе одного инструмента.
- **Calendar.app (macOS)** и **khal/CalDAV (Linux)** остаются доступны как есть (`mac_calendar`,
  `linux_calendar`) — но это два разных инструмента с разным поведением. Google Calendar даёт один
  инструмент, одинаково работающий везде, и его же можно открыть на телефоне.

## Настройка (один раз, ~5 минут)

Google требует, чтобы у каждого приложения был свой OAuth client — общий встроенный ключ для всех
инсталляций JARVIS технически возможен, но означал бы, что один аккаунт разработчика отвечает за
квоты и модерацию доступа для всех пользователей репозитория, что не подходит для проекта с открытым
кодом. Поэтому каждый пользователь создаёт свой (бесплатный) OAuth client — это разовая операция.

1. Откройте [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials).
   Если ещё нет проекта — создайте (кнопка выбора проекта вверху → «New Project», любое имя).
2. Включите Calendar API для этого проекта:
   [console.cloud.google.com/apis/library/calendar-json.googleapis.com](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)
   → кнопка **Enable**.
3. Настройте экран согласия (OAuth consent screen), если Google попросит:
   - User type: **External** (если у вас обычный аккаунт Gmail, не Workspace-организация).
   - Заполните название приложения (например, «JARVIS personal») и свой email в качестве контактного.
   - На шаге Scopes ничего добавлять не нужно (used scope добавится автоматически при первом входе).
   - На шаге Test users добавьте свой же Google-аккаунт (пока приложение не опубликовано — только он
     сможет входить, это нормально для личного использования).
4. Вернитесь на **Credentials** → **Create Credentials** → **OAuth client ID**.
   - Application type: **Desktop app**.
   - Имя — любое, например «JARVIS».
   - Нажмите Create — Google покажет **Client ID** (и иногда Client secret; для Desktop-типа он
     не является секретом в криптографическом смысле, но всё равно скопируйте, если показан).
5. В терминале:
   ```bash
   jarvis calendar setup
   ```
   Вставьте Client ID (и Client secret, если был) когда попросит — откроется браузер, войдите в
   Google-аккаунт и разрешите доступ. После этого:
   ```bash
   jarvis calendar status   # ✔ Авторизовано как you@gmail.com
   jarvis calendar today    # события на сегодня
   ```

## Использование

- Голосом/в чате: «что у меня сегодня по плану», «поставь встречу завтра в 15:00 на час» — модель
  сама вызовет `jarvis_calendar` (today/tomorrow/on_date/create/delete).
- Из терминала: `jarvis calendar today|tomorrow`, `jarvis calendar status`.
- Если календарь ещё не настроен, JARVIS ответит одной фразой, что нужно выполнить
  `jarvis calendar setup`, и не будет переспрашивать в каждом ходе (это фиксируется отдельно,
  без спама).

## Приватность и хранение

- Токен доступа (access + refresh) хранится локально в
  `$HERMES_HOME/plugin-data/jarvis-core/gcalendar_token.json` — никогда не покидает вашу машину и
  не передаётся ни на какой сервер JARVIS/Hermes (весь код запроса — прямые HTTPS-вызовы к
  `googleapis.com` из вашего процесса).
- `jarvis calendar logout` удаляет локальный токен (доступ на стороне Google при этом не
  отзывается — если хотите отозвать полностью, зайдите на
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions)).
- OAuth client id/secret хранятся в `$HERMES_HOME/plugin-data/jarvis-core/gcalendar_client.json` —
  они привязаны к вашему собственному Google Cloud проекту, не к JARVIS/Hermes.

## Диагностика

| Проблема | Решение |
|---|---|
| `jarvis calendar setup` не открывает браузер | Используйте `--no-browser` — команда напечатает ссылку, откройте вручную |
| «Не дождались авторизации» | Не закрывайте терминал до входа в браузере; попробуйте снова, таймаут 3 минуты |
| `invalid_client` при обмене кода на токен | Проверьте, что Client ID/secret скопированы без пробелов; пересоздайте client в Console при сомнении |
| Google предупреждает «This app isn't verified» | Нормально для личного use — ваш собственный проект не проходил ревью Google (не нужно для персонального использования); нажмите Advanced → Go to (unsafe) |
| `access_denied` | Убедитесь, что ваш Google-аккаунт добавлен в Test users на шаге OAuth consent screen |
