#Requires -Version 5.1
<#
  jarvis.ps1 — единая точка входа J.A.R.V.I.S. на Windows (обёртка над hermes + HUD).
  Зеркало bin/jarvis (bash) для Windows. install.ps1 подставляет __HERMES_HOME__ и __PYTHON__
  при установке; можно запускать и напрямую из репозитория для разработки.

  Использование:  jarvis.ps1 <команда> [аргументы...]
  Обычно кладётся в %LOCALAPPDATA%\hermes\bin\jarvis.ps1 и вызывается через ярлык jarvis.cmd
  (Windows не выполняет .ps1 напрямую по имени без расширения — .cmd-обёртка добавляет это).
#>

param(
    [Parameter(Position = 0)] [string]$Command = "",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)] [string[]]$Rest = @()
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

# Windows PowerShell 5.1 по умолчанию декодирует вывод внешних программ (hermes.exe, python…) в
# OEM-кодовой странице консоли, а не в UTF-8 — иначе русский текст из hermes/doctor/HUD-лога
# выводился бы «кракозябрами». Переключаем консоль на UTF-8 при каждом запуске jarvis.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
    chcp 65001 > $null
} catch { }

# ─────────────────────────────── окружение ──────────────────────────────

$HermesHome = $env:HERMES_HOME
if (-not $HermesHome) { $HermesHome = "__HERMES_HOME__" }
if ($HermesHome -eq "__HERMES_HOME__" -or -not (Test-Path $HermesHome -ErrorAction SilentlyContinue)) {
    $fallback = Join-Path $env:LOCALAPPDATA "hermes"
    if (Test-Path $fallback) { $HermesHome = $fallback }
}

$Py = "__PYTHON__"
if (-not (Test-Path $Py -ErrorAction SilentlyContinue) -or $Py -eq "__PYTHON__") {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command py.exe -ErrorAction SilentlyContinue }
    $Py = if ($cmd) { $cmd.Source } else { "python" }
}

$JarvisHome = Join-Path $HermesHome "jarvis"
$HudPort = if ($env:JARVIS_HUD_PORT) { $env:JARVIS_HUD_PORT } else { "8765" }
$HudPidFile = Join-Path $JarvisHome "hud.pid"
$HudLog = Join-Path $HermesHome "logs\jarvis-hud.log"

$env:Path = "$env:LOCALAPPDATA\hermes\bin;$env:Path"

function Say([string]$msg) { Write-Host "◆ $msg" -ForegroundColor Cyan }
function Fail([string]$msg) { Write-Host "✖ $msg" -ForegroundColor Red; exit 1 }
function Need([string]$exe, [string]$hint = "установите её") {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { Fail "нужна команда $exe — $hint" }
}

# ─────────────────────────────── HUD ────────────────────────────────────

function Hud-PidAlive {
    if (-not (Test-Path $HudPidFile)) { return $false }
    $procId = Get-Content $HudPidFile -ErrorAction SilentlyContinue
    if (-not $procId) { return $false }
    return [bool](Get-Process -Id $procId -ErrorAction SilentlyContinue)
}
function Hud-PortAlive {
    try {
        $r = curl.exe -s -m 1 -o NUL -w "%{http_code}" "http://127.0.0.1:$HudPort/api/status" 2>$null
        return $LASTEXITCODE -eq 0 -and $r -match "^\d{3}$"
    } catch { return $false }
}
function Hud-Running { (Hud-PidAlive) -or (Hud-PortAlive) }
function Hud-TaskExists { (schtasks /Query /TN "JARVIS-HUD" 2>$null | Out-Null); $LASTEXITCODE -eq 0 }

function Hud-Start {
    if (Hud-PidAlive) { Say "HUD уже запущен (pid $(Get-Content $HudPidFile))"; return }
    if (Hud-PortAlive) { Say "HUD уже отвечает на :$HudPort (запущен как служба/задача)"; return }
    $server = Join-Path $JarvisHome "hud\server.py"
    if (-not (Test-Path $server)) { Fail "HUD не установлен: $server (переустановите: install.ps1)" }
    New-Item -ItemType Directory -Force -Path (Split-Path $HudLog) | Out-Null
    $p = Start-Process -FilePath $Py -ArgumentList @($server, "--port", $HudPort) `
        -RedirectStandardOutput $HudLog -RedirectStandardError "$HudLog.err" -WindowStyle Hidden -PassThru
    Set-Content -Path $HudPidFile -Value $p.Id
    Start-Sleep -Milliseconds 700
    if (Hud-Running) { Say "HUD → http://127.0.0.1:$HudPort" } else { Write-Host "✖ HUD не стартовал, см. $HudLog" -ForegroundColor Red; exit 1 }
}
function Hud-Stop {
    if (Hud-PidAlive) {
        Stop-Process -Id (Get-Content $HudPidFile) -Force -ErrorAction SilentlyContinue
        Remove-Item $HudPidFile -ErrorAction SilentlyContinue
        Say "HUD остановлен"
    } elseif (Hud-TaskExists) {
        schtasks /End /TN "JARVIS-HUD" 2>$null | Out-Null
        Say "HUD остановлен (задача Планировщика завершена до следующего запуска)"
    } elseif (Hud-PortAlive) {
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
            Where-Object { $_.CommandLine -match "hud[\\/]server\.py" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Say "HUD остановлен"
    } else {
        Remove-Item $HudPidFile -ErrorAction SilentlyContinue
        Say "HUD не запущен"
    }
}

# ─────────────────────────────── Gateway ────────────────────────────────

function Gateway-Running { (& hermes gateway status 2>$null) -match "running|запущен|active" }
function Gateway-TaskExists { schtasks /Query /TN "JARVIS-Gateway" 2>$null | Out-Null; $LASTEXITCODE -eq 0 }
function Gateway-Start {
    if (Gateway-TaskExists) { schtasks /Run /TN "JARVIS-Gateway" 2>$null | Out-Null }
    else { Start-Process -FilePath "hermes" -ArgumentList @("gateway", "start") -WindowStyle Hidden }
}
function Gateway-Stop {
    if (Gateway-TaskExists) {
        schtasks /End /TN "JARVIS-Gateway" 2>$null | Out-Null
        Say "gateway остановлен (задача Планировщика завершена до следующего запуска)"
    } else { & hermes gateway stop }
}

# ─────────────────────────────── usage ──────────────────────────────────

function Usage {
    @"
J.A.R.V.I.S. on Hermes Agent (Windows)

  jarvis                 голосовой чат в терминале (wake word + Ctrl+B), TUI
  jarvis chat [args]     классический CLI Hermes с профилем JARVIS
  jarvis ask "вопрос"    один вопрос — один ответ (без интерактива)
  jarvis hud             запустить HUD и открыть в браузере
  jarvis hud stop|log|status   остановить HUD / показать лог / проверить
  jarvis hush            немедленно заглушить речь (SAPI/edge-tts/озвучка HUD)
  jarvis gateway         запустить gateway (Telegram/Discord/API) в фоне
  jarvis gateway stop    остановить gateway
  jarvis up              всё сразу: gateway + HUD + голосовой TUI
  jarvis status          состояние компонентов
  jarvis brain [stats|review|export|diary|profile|log|backup|restore|sql]   база знаний
  jarvis brain import    первичный импорт: контакты, календарь, заметки → карточки в базе
  jarvis shortcuts       быстрые команды: ярлыки на Рабочем столе + «Отправить» в Проводнике
  jarvis vault [status|add <папка>|remove|search <слова>|list|tree|reindex|open|connect <источник>|note [заголовок]|obsidian-list]   хранилище файлов и проектов (%USERPROFILE%\JARVIS); connect notes-obsidian подключает Obsidian (Windows/Linux/macOS)
  jarvis brief           утренний брифинг прямо сейчас
  jarvis selftest [--fix] проверить все win_* инструменты и права на этой машине (без LLM)
  jarvis heartbeat       одна проверка «нужно ли что-то сказать?» (для Планировщика заданий)
  jarvis doctor [--fix]  самодиагностика: модель, плагины, API, HUD, автозапуск, права, хранилище (--hermes = hermes doctor)
  jarvis update          обновить JARVIS с GitHub (бэкап → установка → перезапуск; откат: --rollback)
  jarvis update --check  только проверить;  --status · --channel stable|main · --auto off|check|auto · --hermes
  jarvis app [open|build|quit|status]  значок JARVIS в системном трее (Python + pystray)
  jarvis version         версии JARVIS и Hermes
  jarvis perms           открыть нужные разделы «Параметры Windows» (микрофон, уведомления, тихий час)
  jarvis calendar [setup|status|today|tomorrow|logout]   Google Calendar (без Outlook)
  jarvis ollama [status|list|recommend|pull <модель>|use <модель> [-vision]]   локальные модели Ollama, без ключей и интернета
  jarvis config          открыть config.yaml Hermes в редакторе
  jarvis logs            хвост логов агента и HUD
"@ | Write-Host
}

# ─────────────────────────────── brain helpers (sqlite через python, без внешнего sqlite3.exe) ──

function Invoke-BrainSql([string]$db, [string]$sql, [switch]$ReadWrite) {
    $mode = if ($ReadWrite) { "" } else { "?mode=ro" }
    $script = @"
import sqlite3, sys
uri = "file:" + sys.argv[1].replace("\\", "/") + "$mode"
con = sqlite3.connect(uri, uri=True)
cur = con.execute(sys.argv[2])
cols = [d[0] for d in cur.description] if cur.description else []
if cols:
    print(" | ".join(cols))
for row in cur.fetchall():
    print(" | ".join(str(v) for v in row))
con.commit()
"@
    & $Py -c $script $db $sql
}

# ─────────────────────────────── dispatch ───────────────────────────────

if ($Command -notin @("", "-h", "--help", "help", "version", "--version", "-v")) {
    if (-not (Test-Path $HermesHome)) { Fail "каталог HERMES_HOME не найден: $HermesHome (переустановите: install.ps1)" }
}

switch ($Command) {
    { $_ -in @("", "voice", "tui") } {
        Say "JARVIS online. Скажите «Hey Jarvis» или нажмите Ctrl+B. /voice, /wake, /brief, /focus, /timer, /screen"
        & hermes --tui @Rest
        break
    }
    "chat" { & hermes chat @Rest; break }
    { $_ -in @("hush", "stop") } {
        Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match "SpeechSynthesizer" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        curl.exe -s -X POST -H "Content-Type: application/json" -d "{}" "http://127.0.0.1:$HudPort/api/hush" 2>$null | Out-Null
        Say "тихо"
        break
    }
    "ask" {
        if ($Rest.Count -eq 0) { Fail 'использование: jarvis ask "вопрос"' }
        & hermes chat -q ($Rest -join " ")
        break
    }
    "hud" {
        $sub = if ($Rest.Count -gt 0) { $Rest[0] } else { "start" }
        switch ($sub) {
            { $_ -in @("start", "open") } { Hud-Start; Start-Process "http://127.0.0.1:$HudPort" -ErrorAction SilentlyContinue; break }
            "status" { if (Hud-Running) { Say "HUD работает → http://127.0.0.1:$HudPort" } else { Say "HUD не запущен"; exit 1 }; break }
            "stop" { Hud-Stop; break }
            { $_ -in @("log", "logs") } { Get-Content $HudLog -Tail 60 -Wait; break }
            "restart" {
                if (Hud-TaskExists) { schtasks /End /TN "JARVIS-HUD" 2>$null | Out-Null; schtasks /Run /TN "JARVIS-HUD" 2>$null | Out-Null; Say "HUD перезапущен (задача Планировщика)" }
                else { Hud-Stop; Hud-Start }
                break
            }
            default { Usage }
        }
        break
    }
    "gateway" {
        $sub = if ($Rest.Count -gt 0) { $Rest[0] } else { "start" }
        switch ($sub) {
            "start" { Gateway-Start; Say "gateway запущен (API :8642)"; break }
            "stop" { Gateway-Stop; break }
            "restart" { Gateway-Stop; Gateway-Start; Say "gateway перезапущен"; break }
            default { & hermes gateway @Rest }
        }
        break
    }
    "up" {
        Gateway-Start; Say "gateway запущен (API :8642)"
        Hud-Start; Start-Process "http://127.0.0.1:$HudPort" -ErrorAction SilentlyContinue
        & hermes --tui
        break
    }
    "status" {
        Write-Host "J.A.R.V.I.S. status" -ForegroundColor Cyan
        $hv = (& hermes --version 2>$null | Select-Object -First 1); if (-not $hv) { $hv = "not found" }
        Write-Host "  hermes      : $hv"
        $model = (& hermes config get model 2>$null); if (-not $model) { $model = "—" }
        Write-Host "  model       : $model"
        Write-Host "  gateway     : $(if (Gateway-Running) {'running'} else {'stopped'})"
        $api = try { curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8642/health 2>$null } catch { "down" }
        Write-Host "  api :8642   : $api"
        Write-Host "  hud  :$HudPort  : $(if (Hud-Running) {'running'} else {'stopped'})"
        $plCount = ((& hermes plugins list 2>$null) | Select-String -Pattern "jarvis" -AllMatches).Matches.Count
        Write-Host "  plugins     : $plCount/3 jarvis-*"
        $wake = (& hermes config get wake_word.enabled 2>$null); if (-not $wake) { $wake = "—" }
        Write-Host "  wake word   : $wake"
        $stt = (& hermes config get stt.provider 2>$null); if (-not $stt) { $stt = "—" }
        $tts = (& hermes config get tts.provider 2>$null); if (-not $tts) { $tts = "—" }
        Write-Host "  stt/tts     : $stt / $tts"
        $taskCount = (schtasks /Query /FO LIST 2>$null | Select-String -Pattern "JARVIS-").Count
        Write-Host "  автозапуск  : $taskCount задач(и) в Планировщике"
        $ver = (& $Py (Join-Path $JarvisHome "update.py") status 2>$null | Select-Object -First 1); if (-not $ver) { $ver = "—" }
        Write-Host "  version     : $ver"
        break
    }
    "brief" { & hermes chat -s jarvis/briefing -q "Сделай брифинг по навыку morning-briefing прямо сейчас."; break }
    "selftest" { & $Py (Join-Path $JarvisHome "selftest.py") @Rest; break }
    "heartbeat" { & hermes chat -s jarvis/heartbeat -q "Heartbeat. Проверь HEARTBEAT.md и ответь NO_REPLY, если ничего не требует внимания."; break }
    "brain" {
        $sub = if ($Rest.Count -gt 0) { $Rest[0] } else { "stats" }
        $rest2 = if ($Rest.Count -gt 1) { $Rest[1..($Rest.Count - 1)] } else { @() }
        $brainDb = Join-Path $HermesHome "plugin-data\jarvis-brain\brain.db"
        switch ($sub) {
            "review" { & hermes chat -s brain-nightly-review -q "Проведи ревизию базы знаний по навыку brain-nightly-review прямо сейчас и дай отчёт."; break }
            "export" { & hermes chat -q "Вызови brain_review export и ответь только путём к файлу."; break }
            "path" { Write-Host $brainDb; break }
            "backup" {
                if (-not (Test-Path $brainDb)) { Fail "базы ещё нет: $brainDb" }
                $dst = "$brainDb.manual-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
                Copy-Item $brainDb $dst; Write-Host "ok: $dst"
                break
            }
            "sql" {
                if (-not (Test-Path $brainDb)) { Fail "базы ещё нет: $brainDb" }
                if ($rest2.Count -gt 0 -and $rest2[0] -eq "--rw") { Invoke-BrainSql $brainDb ($rest2[1..($rest2.Count - 1)] -join " ") -ReadWrite }
                else { Invoke-BrainSql $brainDb ($rest2 -join " ") }
                break
            }
            "log" {
                if (-not (Test-Path $brainDb)) { Fail "базы ещё нет: $brainDb" }
                $n = if ($rest2.Count -gt 0) { $rest2[0] } else { 20 }
                Invoke-BrainSql $brainDb "SELECT ts, actor, op, table_name, row_id FROM changelog ORDER BY id DESC LIMIT $n"
                break
            }
            "diary" {
                if (-not (Test-Path $brainDb)) { Fail "базы ещё нет: $brainDb" }
                $n = if ($rest2.Count -gt 0) { $rest2[0] } else { 7 }
                Invoke-BrainSql $brainDb "SELECT day, summary FROM episodes ORDER BY day DESC LIMIT $n"
                break
            }
            "profile" {
                $profilePath = Join-Path $JarvisHome "PROFILE.md"
                if (Test-Path $profilePath) { Get-Content $profilePath } else { Write-Host "Профиль ещё не выгружен — jarvis brain export" }
                break
            }
            "restore" {
                $latest = Get-ChildItem (Join-Path $HermesHome "plugin-data\jarvis-brain") -Filter "brain.bak-*.db" -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 1
                $src = if ($rest2.Count -gt 0) { $rest2[0] } elseif ($latest) { $latest.FullName } else { $null }
                if (-not $src) { Fail "бэкапов нет (они создаются ночной ревизией и командой jarvis brain backup)" }
                if (-not (Test-Path $src)) { Fail "файл не найден: $src" }
                $a = Read-Host "Откатить базу из $src ? [y/N]"
                if ($a -notin @("y", "Y")) { exit 0 }
                Copy-Item $brainDb "$brainDb.pre-restore-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
                Copy-Item $src $brainDb -Force
                Remove-Item "$brainDb-wal", "$brainDb-shm" -ErrorAction SilentlyContinue
                Write-Host "ok"
                break
            }
            "import" { & hermes chat -s jarvis/brain-import -q "Выполни первичный импорт знаний по навыку brain-import. Спрашивай подтверждение перед записью."; break }
            default {
                if (-not (Test-Path $brainDb)) { Write-Host "База ещё не создана (появится после первого запуска jarvis)"; break }
                Invoke-BrainSql $brainDb "SELECT 'notes: '||COUNT(*) FROM notes WHERE status='active'"
                Invoke-BrainSql $brainDb "SELECT 'entities: '||COUNT(*) FROM entities WHERE status='active'"
                Invoke-BrainSql $brainDb "SELECT 'episodes: '||COUNT(*) FROM episodes"
                Invoke-BrainSql $brainDb "SELECT 'pending turns: '||COUNT(*) FROM turns WHERE digested=0"
                Invoke-BrainSql $brainDb "SELECT 'last review: '||COALESCE(MAX(finished_at),'—') FROM reviews"
                $kb = [math]::Round((Get-Item $brainDb).Length / 1KB)
                Write-Host "file: $brainDb ($kb KB)  ·  markdown: $(Join-Path $JarvisHome 'BRAIN.md')"
            }
        }
        break
    }
    "shortcuts" { & $Py (Join-Path $JarvisHome "make_shortcuts.py") @Rest; break }
    "vault" {
        $vaultPy = Join-Path $HermesHome "plugins\jarvis-brain\vault.py"
        if (-not (Test-Path $vaultPy)) { Fail "плагин jarvis-brain не установлен (install.ps1)" }
        $sub = if ($Rest.Count -gt 0) { $Rest[0] } else { "status" }
        if ($sub -eq "open") {
            & $Py $vaultPy init | Out-Null
            $dir = if ($env:JARVIS_VAULT_DIR) { $env:JARVIS_VAULT_DIR } else { Join-Path $env:USERPROFILE "JARVIS" }
            Start-Process explorer.exe $dir
        } else { & $Py $vaultPy @Rest }
        break
    }
    "doctor" {
        if ($Rest.Count -gt 0 -and $Rest[0] -eq "--hermes") { & hermes doctor @($Rest[1..($Rest.Count - 1)]) }
        else {
            $doctorPy = Join-Path $JarvisHome "doctor.py"
            if (-not (Test-Path $doctorPy)) { Fail "doctor.py не установлен (install.ps1)" }
            & $Py $doctorPy @Rest
        }
        break
    }
    "update" {
        $sub = if ($Rest.Count -gt 0) { $Rest[0] } else { "" }
        $updatePy = Join-Path $JarvisHome "update.py"
        switch -Regex ($sub) {
            "^(--check|check)$" { & $Py $updatePy check @($Rest[1..($Rest.Count - 1)]); break }
            "^(--rollback|rollback)$" { & $Py $updatePy rollback; break }
            "^(--status|status)$" { & $Py $updatePy status @($Rest[1..($Rest.Count - 1)]); break }
            "^(--channel|channel)$" { & $Py $updatePy set channel $Rest[1]; break }
            "^(--auto|auto)$" { & $Py $updatePy set auto $Rest[1]; break }
            "^--hermes$" { & hermes update; break }
            "^(--yes|-y|)$" { & $Py $updatePy apply; break }
            "^--force$" { & $Py $updatePy apply --force; break }
            default { Write-Host "jarvis update [--check|--rollback|--status|--force|--channel stable|main|--auto off|check|auto|--hermes]"; exit 2 }
        }
        break
    }
    { $_ -in @("version", "--version", "-v") } {
        $ver = Get-Content (Join-Path $JarvisHome "VERSION") -ErrorAction SilentlyContinue
        if (-not $ver) { $ver = "?" }
        $hv = (& hermes --version 2>$null | Select-Object -First 1); if (-not $hv) { $hv = "?" }
        Write-Host "JARVIS $ver · Hermes $hv"
        break
    }
    "app" {
        $sub = if ($Rest.Count -gt 0) { $Rest[0] } else { "open" }
        $trayPyw = Join-Path $JarvisHome "tray\jarvis_tray.pyw"
        $trayPidFile = Join-Path $JarvisHome "tray.pid"
        switch ($sub) {
            "open" {
                if (-not (Test-Path $trayPyw)) { Fail "трей-приложение не установлено — install.ps1 (шаг tray)" }
                $pyw = $Py -replace "python\.exe$", "pythonw.exe"
                if (-not (Test-Path $pyw)) { $pyw = $Py }
                $p = Start-Process -FilePath $pyw -ArgumentList @($trayPyw) -WindowStyle Hidden -PassThru
                Set-Content $trayPidFile $p.Id
                Say "JARVIS в системном трее запущен"
                break
            }
            "build" { Write-Host "На Windows трей-приложение — чистый Python (pystray), пересборка не требуется: install.ps1 -Yes переустановит зависимости."; break }
            "quit" {
                if (Test-Path $trayPidFile) { Stop-Process -Id (Get-Content $trayPidFile) -Force -ErrorAction SilentlyContinue; Remove-Item $trayPidFile -ErrorAction SilentlyContinue }
                Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
                    Where-Object { $_.CommandLine -match "jarvis_tray\.pyw" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
                break
            }
            "status" {
                $running = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
                    Where-Object { $_.CommandLine -match "jarvis_tray\.pyw" }
                if ($running) { Write-Host "трей-приложение запущено (pid $($running[0].ProcessId))" } else { Write-Host "трей-приложение не запущено" }
                break
            }
            default { Write-Host "jarvis app [open|build|quit|status]" }
        }
        break
    }
    "perms" {
        Start-Process "ms-settings:privacy-microphone"; Start-Sleep -Seconds 1
        Start-Process "ms-settings:notifications"; Start-Sleep -Seconds 1
        Start-Process "ms-settings:quiethours"; Start-Sleep -Seconds 1
        Start-Process "ms-settings:privacy-webcam"
        break
    }
    "calendar" {
        $calPy = Join-Path $JarvisHome "calendar_cli.py"
        if (-not (Test-Path $calPy)) { Fail "calendar_cli.py не установлен (переустановите: install.ps1)" }
        & $Py $calPy @Rest
        break
    }
    "ollama" {
        $ollamaPy = Join-Path $JarvisHome "ollama_local.py"
        if (-not (Test-Path $ollamaPy)) { Fail "ollama_local.py не установлен (переустановите: install.ps1)" }
        & $Py $ollamaPy @Rest
        break
    }
    "config" { & hermes config edit; break }
    "logs" {
        $agentLog = Join-Path $HermesHome "logs\agent.log"
        if (Test-Path $agentLog) { Get-Content $agentLog -Tail 40 }
        if (Test-Path $HudLog) { Get-Content $HudLog -Tail 40 }
        try { & hermes logs --follow } catch { Write-Verbose "hermes logs --follow недоступен: $($_.Exception.Message)" }
        break
    }
    { $_ -in @("-h", "--help", "help") } { Usage; break }
    default { & hermes $Command @Rest }
}
