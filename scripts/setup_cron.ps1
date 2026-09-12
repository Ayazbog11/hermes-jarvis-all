#Requires -Version 5.1
<#
  Создаёт стандартные фоновые задачи JARVIS через встроенный cron Hermes.
  Зеркало scripts/setup_cron.sh — сам cron кроссплатформенный (это фича Hermes,
  не ОС), меняется только обвязка запуска.
  Безопасно запускать повторно: существующие задачи с теми же именами пропускаются.
#>

$ErrorActionPreference = "Stop"
$env:Path = "$env:LOCALAPPDATA\hermes\bin;$env:Path"

# Windows PowerShell 5.1 считает вывод внешней программы в stderr завершающей ошибкой при
# $ErrorActionPreference = "Stop", даже если он тут же отбрасывается через "2>$null"
# (https://github.com/PowerShell/PowerShell/issues/3996) — оборачиваем такие вызовы в Quiet.
function Quiet([scriptblock]$Block) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try { & $Block } finally { $ErrorActionPreference = $prevEap }
}

function Have([string]$name) {
    $list = Quiet { & hermes cron list 2>$null }
    return ($list -join "`n") -match [regex]::Escape($name)
}

function Mk([string]$name, [string]$schedule, [string]$prompt, [string]$skill = "") {
    if (Have $name) { Write-Host "  = $name (уже есть)"; return }
    Quiet {
        if ($skill) {
            & hermes cron create $schedule $prompt --name $name --skill $skill 2>$null | Out-Null
        } else {
            & hermes cron create $schedule $prompt --name $name 2>$null | Out-Null
        }
    }
    if ($LASTEXITCODE -eq 0) { Write-Host "  + $name" } else { Write-Host "  ✖ $name (не удалось создать)" }
}

Mk "JARVIS: утренний брифинг" "every day at 08:00" `
   "Сделай утренний брифинг по навыку morning-briefing. Коротко." "jarvis/briefing"
Mk "JARVIS: вечерний итог" "every day at 21:00" `
   "Сделай вечерний итог дня: что сделано (session_search за сегодня), что перенести на завтра, события календаря на завтра (win_calendar tomorrow). Коротко." "jarvis/briefing"
Mk "JARVIS: ночная ревизия базы знаний" "every day at 03:30" `
   "Проведи ночную ревизию базы знаний по навыку brain-nightly-review: brain_review maintain -> digest_queue/save_episode -> plan -> apply -> export -> finish. Если изменений нет - ответь ровно: [SILENT]" "brain-nightly-review"
Mk "JARVIS: синхронизация памяти" "every sunday at 20:00" `
   "1) brain_review profile - получи самое важное из базы знаний. 2) Сравни со встроенной памятью (memory: USER.md/MEMORY.md): факты из памяти, которых нет в базе - перенеси через brain_remember; устаревшее в памяти удали; убедись, что в USER.md есть 10-15 самых важных пунктов профиля (importance >= 4) - не больше. Отчитайся в двух предложениях."

if ($env:JARVIS_HEARTBEAT -ne "0") {
    Mk "JARVIS: heartbeat" "every 3 hours" `
       "Heartbeat. Прочитай %LOCALAPPDATA%\hermes\jarvis\HEARTBEAT.md и действуй по навыку jarvis/heartbeat. Если ничего не требует внимания - ответь ровно: NO_REPLY" "jarvis/heartbeat"
}

if (Have "JARVIS: контроль батареи") {
    Write-Host "  ! задача «контроль батареи» устарела (теперь watchdog без LLM) - удалите: hermes cron remove <id>"
}
Write-Host "Готово. Список: hermes cron list"
