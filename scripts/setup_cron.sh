#!/usr/bin/env bash
# Создаёт стандартные фоновые задачи JARVIS через встроенный cron Hermes.
# Безопасно запускать повторно: существующие задачи с теми же именами пропускаются.
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
have(){ hermes cron list 2>/dev/null | grep -q -F "$1"; }
mk(){ # mk "name" "schedule" "prompt" [skill]
  if have "$1"; then echo "  = $1 (уже есть)"; return; fi
  if [[ -n "${4:-}" ]]; then hermes cron create "$2" "$3" --name "$1" --skill "$4" >/dev/null && echo "  + $1"
  else hermes cron create "$2" "$3" --name "$1" >/dev/null && echo "  + $1"; fi
}
mk "JARVIS: утренний брифинг" "every day at 08:00" \
   "Сделай утренний брифинг по навыку morning-briefing. Коротко." "jarvis/briefing"
mk "JARVIS: вечерний итог" "every day at 21:00" \
   "Сделай вечерний итог дня: что сделано (session_search за сегодня), что перенести на завтра, события календаря на завтра (jarvis_calendar tomorrow). Коротко." "jarvis/briefing"
# brain-nightly-review — навык ПЛАГИНА jarvis-brain (register_skill), а не файл в общем дереве
# ~/.hermes/skills/ — резолвится ТОЛЬКО через квалифицированное имя "<plugin>:<skill>"
# (см. hermes_cli.plugins.PluginContext.register_skill: "становится доступным как
# '<plugin_name>:<name>' через skill_view()... не входит в плоское дерево ~/.hermes/skills/").
# Раньше здесь был голый "brain-nightly-review" — cron падал с "Skill 'brain-nightly-review'
# not found", потому что плоский скан ~/.hermes/skills/ не видит навыки, зарегистрированные
# плагинами напрямую.
mk "JARVIS: ночная ревизия базы знаний" "every day at 03:30" \
   "Проведи ночную ревизию базы знаний по навыку brain-nightly-review: brain_review maintain → digest_queue/save_episode → plan → apply → export → finish. Если изменений нет — ответь ровно: [SILENT]" "jarvis-brain:brain-nightly-review"
mk "JARVIS: синхронизация памяти" "every sunday at 20:00" \
   "1) brain_review profile — получи самое важное из базы знаний. 2) Сравни со встроенной памятью (memory: USER.md/MEMORY.md): факты из памяти, которых нет в базе — перенеси через brain_remember; устаревшее в памяти удали; убедись, что в USER.md есть 10–15 самых важных пунктов профиля (importance ≥4) — не больше. Отчитайся в двух предложениях."
# С 1.8 основную проактивность делают локальные триггеры jarvis-core (события, без LLM); cron-heartbeat остаётся редкой страховкой
if [[ "${JARVIS_HEARTBEAT:-1}" == "1" ]]; then
  mk "JARVIS: heartbeat" "every 3 hours" \
     "Heartbeat. Прочитай ~/.hermes/jarvis/HEARTBEAT.md и действуй по навыку jarvis/heartbeat. Если ничего не требует внимания — ответь ровно: NO_REPLY" "jarvis/heartbeat"
fi
# Старая LLM-задача контроля батареи больше не нужна — её заменил локальный watchdog jarvis-core
hermes cron list 2>/dev/null | grep -q -F "JARVIS: контроль батареи" && echo "  ! задача «контроль батареи» устарела (теперь watchdog без LLM) — удалите: hermes cron remove <id>"
echo "Готово. Список: hermes cron list"
