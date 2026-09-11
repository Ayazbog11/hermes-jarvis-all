#Requires -Version 5.1
<#
  ═══════════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. on Hermes Agent — установщик для Windows 10/11 (native, без WSL)
  ═══════════════════════════════════════════════════════════════════════════

  Что делает (идемпотентно — можно запускать повторно):
   1. Проверяет Windows 10/11, PowerShell 5.1+, архитектуру.
   2. Устанавливает Hermes Agent (официальный install.ps1 NousResearch), если его ещё нет.
   3. Ставит voice-extras: faster-whisper, edge-tts, sounddevice, numpy, openWakeWord (best effort).
   4. Копирует плагины jarvis-core / jarvis-windows / jarvis-brain в %HERMES_HOME%\plugins.
   5. Ставит SOUL.md (личность), навыки, хук boot, cron-задачи.
   6. Аккуратно вливает config.jarvis.windows.yaml в %HERMES_HOME%\config.yaml.
   7. Включает OpenAI-совместимый API (порт 8642) для HUD.
   8. Устанавливает команду `jarvis` (jarvis.ps1 + jarvis.cmd) и автозапуск через Планировщик заданий.
   9. Ставит трей-приложение (pystray) и HUD.
  10. Запускает doctor.py и печатает следующие шаги.

  Флаги:
    -Yes                  не спрашивать подтверждений (для авто-обновления)
    -NoScheduledTask       не регистрировать автозапуск в Планировщике заданий
    -NoVoice               пропустить голосовые extras (STT/TTS/wake word)
    -NoExtraTools          не пытаться доустанавливать ffmpeg и т.п. через winget
    -NoCron                не создавать фоновые cron-задачи Hermes (брифинг и т.д.)
    -NoApp                 не ставить трей-приложение
    -HermesHome <path>     нестандартный HERMES_HOME (по умолчанию %LOCALAPPDATA%\hermes)

  Переменные окружения (для updater, как JARVIS_QUIET на macOS):
    JARVIS_QUIET=1  JARVIS_COMMIT=sha  JARVIS_CHANNEL=stable|main  JARVIS_AUTO_UPDATE=off|check|auto
#>

param(
    [switch]$Yes,
    [switch]$NoScheduledTask,
    [switch]$NoVoice,
    [switch]$NoExtraTools,
    [switch]$NoCron,
    [switch]$NoApp,
    [string]$HermesHome = ""
)

$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 по умолчанию декодирует stdout/stderr ВНЕШНИХ программ (hermes.exe,
# schtasks.exe, winget…) в OEM-кодовой странице консоли (обычно cp866 на русской Windows), а не
# в UTF-8, в котором эти программы реально пишут текст на английском/русском вперемешку — отсюда
# «кракозябры» вида «тФВ jarvis-brain тФВ» в таблицах диагностики. Переключаем консоль на UTF-8
# в начале скрипта, чтобы весь захватываемый вывод декодировался и печатался корректно.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
    chcp 65001 > $null
} catch { }

# ─── параметры ────────────────────────────────────────────────────────────

$JarvisSrc = $PSScriptRoot
if (-not $HermesHome) { $HermesHome = $env:HERMES_HOME }
if (-not $HermesHome) { $HermesHome = Join-Path $env:LOCALAPPDATA "hermes" }
$JarvisHomeDir = Join-Path $HermesHome "jarvis"
$BinDir = Join-Path $HermesHome "bin"
$JarvisVersion = (Get-Content (Join-Path $JarvisSrc "VERSION") -ErrorAction SilentlyContinue)
if (-not $JarvisVersion) { $JarvisVersion = "0.0.0" }
$JarvisRepo = if ($env:JARVIS_REPO) { $env:JARVIS_REPO } else { "Ayazbog11/hermes-jarvis-all" }
$Quiet = $env:JARVIS_QUIET -eq "1"

# ─── оформление ───────────────────────────────────────────────────────────

function Step([string]$msg) { Write-Host ""; Write-Host "▶ $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "  ✔ $msg" -ForegroundColor Green }
function WarnMsg([string]$msg) { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Die([string]$msg) { Write-Host "  ✖ $msg" -ForegroundColor Red; exit 1 }
function AskYN([string]$question) {
    if ($Yes) { return $true }
    $a = Read-Host "  $question [Y/n]"
    return ($a -eq "" -or $a -match "^[YyДд]")
}

Write-Host @"

     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
        on Hermes Agent  ·  Windows installer
"@

# ─── 1. пререквизиты ──────────────────────────────────────────────────────

Step "Проверка системы"
if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
    Die "Этот установщик только для Windows. Для macOS используйте install.sh, для Linux — install.sh (WSL2)."
}
$osInfo = Get-CimInstance Win32_OperatingSystem
Ok "$($osInfo.Caption) $($osInfo.Version) · $env:PROCESSOR_ARCHITECTURE"

if ($PSVersionTable.PSVersion.Major -lt 5) { Die "Нужен PowerShell 5.1 или новее." }
Ok "PowerShell $($PSVersionTable.PSVersion)"

if ($NoExtraTools) {
    WarnMsg "пропускаю ffmpeg и системные утилиты (-NoExtraTools)"
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Step "Системные зависимости (winget)"
    $pkgs = @("Gyan.FFmpeg")
    foreach ($p in $pkgs) {
        $installed = winget list --id $p -e 2>$null | Select-String $p
        if ($installed) { Ok $p }
        else {
            Write-Host "  … устанавливаю $p" -ForegroundColor DarkGray
            winget install --id $p -e --accept-source-agreements --accept-package-agreements --silent 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { Ok $p } else { WarnMsg "не удалось установить $p (не критично, можно вручную)" }
        }
    }
} else {
    WarnMsg "winget не найден — ffmpeg пропущен, поставьте вручную при необходимости (-NoExtraTools чтобы убрать это сообщение)"
}

# ─── 2. Hermes Agent ──────────────────────────────────────────────────────

Step "Hermes Agent"
$hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
if (-not $hermesCmd -and (Test-Path (Join-Path $BinDir "hermes.exe"))) {
    $env:Path = "$BinDir;$env:Path"
    $hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
}
if ($hermesCmd) {
    Ok "уже установлен: $($hermesCmd.Source)"
} else {
    Write-Host "  Устанавливаю Hermes Agent официальным скриптом (uv + Python + репозиторий)…"
    try {
        Invoke-Expression (Invoke-RestMethod -Uri "https://hermes-agent.nousresearch.com/install.ps1")
    } catch {
        Die "Не удалось установить Hermes Agent автоматически: $($_.Exception.Message). См. https://hermes-agent.nousresearch.com/docs"
    }
    $env:Path = "$BinDir;$env:Path"
}
$hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
if (-not $hermesCmd) { Die "Команда hermes недоступна. Откройте новое окно PowerShell и запустите install.ps1 снова." }
if (-not (Test-Path $HermesHome)) { Die "Не найден каталог Hermes: $HermesHome" }
$hv = (& hermes --version 2>$null | Select-Object -First 1)
Ok "hermes $hv"

# venv/интерпретатор Hermes (для pip-extras и запуска наших скриптов).
# ВАЖНО: официальный установщик Hermes на Windows кладёт venv не в $HermesHome\venv, а в
# $HermesHome\hermes-agent\venv (полный git-чекаут Hermes живёт в подпапке hermes-agent —
# см. install.sh/install.linux.sh, где на POSIX используется тот же $HERMES_REPO/venv).
# Раньше здесь ошибочно предполагался путь $HermesHome\venv, из-за чего $env:VIRTUAL_ENV
# указывал в никуда и `uv pip install` падал с «Failed to inspect Python interpreter from
# active virtual environment» — venv для uv просто не существовал по этому пути.
$HermesRepoDir = Join-Path $HermesHome "hermes-agent"
$VenvDir = Join-Path $HermesRepoDir "venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    # запасной путь на случай нестандартной раскладки/старых установок Hermes
    $legacyVenvPy = Join-Path $HermesHome "venv\Scripts\python.exe"
    if (Test-Path $legacyVenvPy) {
        $VenvDir = Join-Path $HermesHome "venv"
        $VenvPy = $legacyVenvPy
    } else {
        $pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $pyCmd) { $pyCmd = Get-Command py.exe -ErrorAction SilentlyContinue }
        $VenvPy = if ($pyCmd) { $pyCmd.Source } else { Die "Python не найден ни в venv Hermes, ни в PATH." }
        $VenvDir = $null
    }
}
Ok "python: $VenvPy"

function Invoke-Pip([string[]]$pipArgs) {
    if ($VenvDir -and (Get-Command uv -ErrorAction SilentlyContinue)) {
        $env:VIRTUAL_ENV = $VenvDir
        & uv pip install -q @pipArgs 2>$null
    } else {
        & $VenvPy -m pip install -q @pipArgs
    }
}

# ─── 3. голосовые extras ──────────────────────────────────────────────────

if (-not $NoVoice) {
    Step "Голос: faster-whisper (STT), Edge TTS, openWakeWord (wake word)"
    try {
        Invoke-Pip @("faster-whisper", "edge-tts", "sounddevice", "numpy")
        Invoke-Pip @("openwakeword")
        Ok "voice extras установлены"
    } catch {
        WarnMsg "часть голосовых пакетов не установилась — см. docs/TROUBLESHOOTING.md ($($_.Exception.Message))"
    }
}

if (-not $NoApp) {
    Step "Трей-приложение: pystray, pillow"
    try {
        Invoke-Pip @("pystray", "pillow")
        Ok "pystray/pillow установлены"
    } catch {
        WarnMsg "pystray/pillow не установились — jarvis app будет недоступен ($($_.Exception.Message))"
    }
}

# ─── 4. плагины ───────────────────────────────────────────────────────────

Step "Плагины JARVIS -> $HermesHome\plugins"
New-Item -ItemType Directory -Force -Path (Join-Path $HermesHome "plugins") | Out-Null
$plugins = @("jarvis-core", "jarvis-windows", "jarvis-brain")
foreach ($plug in $plugins) {
    if (-not (Test-Path (Join-Path $JarvisSrc "plugins\$plug\plugin.yaml"))) {
        Die "в архиве нет плагина $plug — скачайте проект заново"
    }
}
foreach ($plug in $plugins) {
    $dst = Join-Path $HermesHome "plugins\$plug"
    Remove-Item -Recurse -Force $dst -ErrorAction SilentlyContinue
    Copy-Item -Recurse -Force (Join-Path $JarvisSrc "plugins\$plug") $dst
    Ok $plug
}

# ─── 5. личность, навыки, хуки, HUD ────────────────────────────────────────

Step "Личность (SOUL.md), навыки, хуки, HUD"
$soulDst = Join-Path $HermesHome "SOUL.md"
if ((Test-Path $soulDst) -and -not (Select-String -Path $soulDst -Pattern "J\.A\.R\.V\.I\.S" -Quiet -ErrorAction SilentlyContinue)) {
    Copy-Item $soulDst "$soulDst.bak.$([int][double]::Parse((Get-Date -UFormat %s)))"
    WarnMsg "ваш прежний SOUL.md сохранён как SOUL.md.bak.*"
}
Copy-Item (Join-Path $JarvisSrc "config\SOUL.md") $soulDst -Force
Ok "SOUL.md"

New-Item -ItemType Directory -Force -Path (Join-Path $HermesHome "skills\jarvis") | Out-Null
Copy-Item -Recurse -Force (Join-Path $JarvisSrc "skills\*") (Join-Path $HermesHome "skills\jarvis")
Ok "skills/jarvis/*"

New-Item -ItemType Directory -Force -Path (Join-Path $HermesHome "hooks") | Out-Null
$hookDst = Join-Path $HermesHome "hooks\jarvis-boot"
Remove-Item -Recurse -Force $hookDst -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force (Join-Path $JarvisSrc "hooks\jarvis-boot") $hookDst
Ok "hooks/jarvis-boot"
$bootMd = Join-Path $HermesHome "BOOT.md"
if (-not (Test-Path $bootMd)) { Copy-Item (Join-Path $JarvisSrc "config\BOOT.md") $bootMd }

New-Item -ItemType Directory -Force -Path (Join-Path $HermesHome "skill-bundles") | Out-Null
Copy-Item (Join-Path $JarvisSrc "skill-bundles\jarvis.windows.yaml") (Join-Path $HermesHome "skill-bundles\jarvis.yaml") -Force
Ok "skill-bundles/jarvis.yaml  (/jarvis в чате)"

New-Item -ItemType Directory -Force -Path $JarvisHomeDir | Out-Null
Copy-Item (Join-Path $JarvisSrc "config\.env.example") (Join-Path $JarvisHomeDir "env.example") -Force

$hudDst = Join-Path $JarvisHomeDir "hud"
Remove-Item -Recurse -Force $hudDst -ErrorAction SilentlyContinue
Copy-Item -Recurse -Force (Join-Path $JarvisSrc "hud") $hudDst
Copy-Item (Join-Path $JarvisSrc "config\config.jarvis.windows.yaml") (Join-Path $JarvisHomeDir "config.jarvis.yaml") -Force
foreach ($f in @("merge_config.py", "selftest.py", "update.py", "doctor.py", "make_shortcuts.py", "setup_scheduled_tasks.py", "calendar_cli.py", "ollama_local.py", "usage_report.py")) {
    Copy-Item (Join-Path $JarvisSrc "scripts\$f") (Join-Path $JarvisHomeDir $f) -Force
}
Copy-Item (Join-Path $JarvisSrc "scripts\setup_cron.ps1") (Join-Path $JarvisHomeDir "setup_cron.ps1") -Force

$trayDst = Join-Path $JarvisHomeDir "tray"
Remove-Item -Recurse -Force $trayDst -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $trayDst | Out-Null
Copy-Item (Join-Path $JarvisSrc "app-windows\jarvis_tray.pyw") (Join-Path $trayDst "jarvis_tray.pyw") -Force

Copy-Item (Join-Path $JarvisSrc "VERSION") (Join-Path $JarvisHomeDir "VERSION") -Force
if (Test-Path (Join-Path $JarvisSrc "config\HEARTBEAT.md")) {
    Copy-Item (Join-Path $JarvisSrc "config\HEARTBEAT.md") $JarvisHomeDir -Force
}
Ok "HUD -> $JarvisHomeDir\hud"

# ─── 6. конфигурация ──────────────────────────────────────────────────────

Step "Конфигурация $HermesHome\config.yaml"
$cfgPath = Join-Path $HermesHome "config.yaml"
if (-not (Test-Path $cfgPath)) {
    try { & hermes config | Out-Null } catch {}
}
if (-not (Test-Path $cfgPath)) { Set-Content -Path $cfgPath -Value "{}" }
Copy-Item $cfgPath "$cfgPath.bak.jarvis" -Force
try {
    & $VenvPy (Join-Path $JarvisSrc "scripts\merge_config.py") (Join-Path $JarvisSrc "config\config.jarvis.windows.yaml") $cfgPath
    Ok "ключи JARVIS добавлены (бэкап: config.yaml.bak.jarvis)"
} catch {
    WarnMsg "merge не удался — примените config/config.jarvis.windows.yaml вручную"
}

# ─── 7. API-сервер для HUD ─────────────────────────────────────────────────

Step "OpenAI-совместимый API Hermes (для HUD)"
$envFile = Join-Path $HermesHome ".env"
if (-not (Test-Path $envFile)) { New-Item -ItemType File -Path $envFile | Out-Null }
$envLines = Get-Content $envFile -ErrorAction SilentlyContinue
function EnvHas([string]$key) { ($envLines | Where-Object { $_ -match "^$key=\S" }).Count -gt 0 }
function EnvSet([string]$key, [string]$value) {
    $script:envLines = $script:envLines | Where-Object { $_ -notmatch "^$key=" }
    $script:envLines += "$key=$value"
}
if (-not (EnvHas "API_SERVER_ENABLED")) { EnvSet "API_SERVER_ENABLED" "true" }
if (-not (EnvHas "API_SERVER_KEY")) {
    $bytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $key = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    EnvSet "API_SERVER_KEY" $key
    Ok "сгенерирован API_SERVER_KEY"
} else { Ok "API_SERVER_KEY уже задан" }
if (-not (EnvHas "API_SERVER_HOST")) { EnvSet "API_SERVER_HOST" "127.0.0.1" }
Set-Content -Path $envFile -Value $envLines

# ─── 8. команда jarvis ─────────────────────────────────────────────────────

Step "Команда ``jarvis``"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$jarvisPs1 = (Get-Content (Join-Path $JarvisSrc "bin\jarvis.ps1") -Raw).Replace("__HERMES_HOME__", $HermesHome).Replace("__PYTHON__", $VenvPy)
Set-Content -Path (Join-Path $BinDir "jarvis.ps1") -Value $jarvisPs1
Copy-Item (Join-Path $JarvisSrc "bin\jarvis.cmd") (Join-Path $BinDir "jarvis.cmd") -Force
Ok "$BinDir\jarvis.ps1 + jarvis.cmd"

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$BinDir", "User")
    Ok "добавлено в PATH пользователя (перезапустите терминал)"
} else {
    Ok "уже в PATH"
}

# install.json — по нему работает автообновление (jarvis update); настройки канала/режима сохраняются
$writeInstallJson = @'
import json, sys, datetime, pathlib
# args[6:] дополняем пустыми строками на случай, если вызывающая сторона (PowerShell отбрасывает
# позиционные $null-аргументы внешних команд) передала меньше 6 значений — не падаем молча.
args = (sys.argv[1:] + [""] * 6)[:6]
p, ver, commit, repo, channel, auto = pathlib.Path(args[0]), *args[1:]
old = {}
try: old = json.loads(p.read_text(encoding="utf-8"))
except Exception: pass
data = {**old, "version": ver, "commit": commit or old.get("commit", ""), "repo": repo,
        "channel": channel or old.get("channel", "stable"), "auto_update": auto or old.get("auto_update", "auto"),
        "installed_at": datetime.datetime.now().replace(microsecond=0).isoformat()}
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
'@
$installJsonScript = Join-Path $env:TEMP "jarvis-write-install-json.py"
Set-Content -Path $installJsonScript -Value $writeInstallJson -Encoding UTF8
# $env:JARVIS_COMMIT/$env:JARVIS_CHANNEL/$env:JARVIS_AUTO_UPDATE обычно не заданы при первой
# установке (их выставляет только jarvis update). PowerShell при вызове внешней программы
# полностью ОТБРАСЫВАЕТ позиционные аргументы со значением $null — а не передаёт пустую строку,
# как можно было бы ожидать. Из-за этого пропадали сразу 3 аргумента и python получал 3 вместо 6
# ("not enough values to unpack"). Подставляем явную пустую строку вместо $null.
$commitArg = if ($env:JARVIS_COMMIT) { $env:JARVIS_COMMIT } else { "" }
$channelArg = if ($env:JARVIS_CHANNEL) { $env:JARVIS_CHANNEL } else { "" }
$autoArg = if ($env:JARVIS_AUTO_UPDATE) { $env:JARVIS_AUTO_UPDATE } else { "" }
& $VenvPy $installJsonScript (Join-Path $JarvisHomeDir "install.json") $JarvisVersion $commitArg $JarvisRepo $channelArg $autoArg
Remove-Item $installJsonScript -ErrorAction SilentlyContinue
Ok "install.json: версия $JarvisVersion"

# ─── 8b. автозапуск (Планировщик заданий) ──────────────────────────────────

if (-not $NoScheduledTask -and (AskYN "Настроить автозапуск HUD и gateway при входе в систему (Планировщик заданий)?")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $HermesHome "logs") | Out-Null
    $stArgs = @("install", "--home", $HermesHome, "--python", $VenvPy)
    if ($NoApp) { $stArgs += "--no-app" }
    if ($NoCron) { $stArgs += "--no-cron" }
    & $VenvPy (Join-Path $JarvisHomeDir "setup_scheduled_tasks.py") @stArgs
}

# ─── 9. трей-приложение ────────────────────────────────────────────────────

if (-not $NoApp) {
    Step "JARVIS в системном трее (значок статуса, HUD, голос, обновления)"
    if (Test-Path (Join-Path $trayDst "jarvis_tray.pyw")) {
        Ok "$trayDst\jarvis_tray.pyw"
        if (-not $Quiet) {
            $pyw = $VenvPy -replace "python\.exe$", "pythonw.exe"
            if (-not (Test-Path $pyw)) { $pyw = $VenvPy }
            try {
                Start-Process -FilePath $pyw -ArgumentList @(Join-Path $trayDst "jarvis_tray.pyw") -WindowStyle Hidden
                Ok "запущено"
            } catch { WarnMsg "не удалось запустить сейчас — jarvis app open" }
        }
    } else {
        WarnMsg "трей-приложение не установлено. Всё работает через команду jarvis; попробуйте: jarvis app open"
    }
}

# ─── 10. cron-задачи JARVIS ─────────────────────────────────────────────────

Step "Фоновые задачи (утренний брифинг, вечерний итог, ночная ревизия)"
if (-not $NoCron -and (AskYN "Создать cron-задачи JARVIS (брифинг 08:00, вечерний итог 21:00, ночная ревизия 03:30, heartbeat)?")) {
    try { & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $JarvisHomeDir "setup_cron.ps1") }
    catch { WarnMsg "cron не настроен — можно позже: powershell -File `"$JarvisHomeDir\setup_cron.ps1`"" }
}

if ($Quiet) { Write-Host "JARVIS $JarvisVersion установлен (тихий режим updater)"; exit 0 }

# ─── 11. модель ─────────────────────────────────────────────────────────────

Step "Провайдер LLM"
$model = (& hermes config get model 2>$null)
if ($model -and $model.Trim()) {
    Ok "модель: $model"
    Write-Host "  … проверяю, что модель отвечает" -ForegroundColor DarkGray
    $ping = ""
    $job = Start-Job { & hermes chat -q "Ответь одним словом: ok" 2>&1 }
    if (Wait-Job $job -Timeout 90) { $ping = (Receive-Job $job | Out-String) } else { Stop-Job $job }
    Remove-Job $job -Force -ErrorAction SilentlyContinue
    $ping = $ping.Trim()
    if (-not $ping -or $ping -match "error code|http [45]\d\d|traceback|\b(401|403|405|429)\b") {
        WarnMsg "модель настроена, но НЕ отвечает: $(if ($ping) { $ping.Substring(0, [Math]::Min(400, $ping.Length)) } else { 'пустой ответ' })"
        if (-not $Yes -and (AskYN "Открыть мастер выбора модели сейчас (рекомендую OpenRouter или Ollama)?")) { & hermes model }
    } else { Ok "модель отвечает" }
} else {
    WarnMsg "Модель не настроена. Сейчас откроется мастер — выберите провайдера (OpenRouter / Anthropic / OpenAI / Nous Portal / Ollama)."
    if (-not $Yes) { & hermes model }
}

# ─── 12. доктор ──────────────────────────────────────────────────────────────

Step "Диагностика"
$pluginsList = (& hermes plugins list 2>$null | Out-String)
if ($pluginsList -notmatch "(?i)jarvis-core") {
    & hermes plugins enable jarvis-core jarvis-windows jarvis-brain 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "плагины включены" }
    else { WarnMsg "плагины не отображаются — выполните: hermes plugins enable jarvis-core jarvis-windows jarvis-brain" }
}
& hermes plugins list 2>$null | Select-String -Pattern "jarvis" | Write-Host
& $VenvPy (Join-Path $JarvisHomeDir "doctor.py") --quick --fix 2>$null | Out-Null

# ─── итог ────────────────────────────────────────────────────────────────────

Write-Host @"

══════════════════════════════════════════════════════════════════════
 J.A.R.V.I.S. установлен.

 Права/настройка Windows (один раз, иначе часть команд не сработает):
   Параметры Windows -> Конфиденциальность и безопасность ->
     • Микрофон             -> разрешить приложениям (и рабочему столу)
     • Уведомления           -> разрешить JARVIS/PowerShell показывать баллоны
     • Тихий час (Focus Assist) -> нет публичного API — переключается вручную
   Outlook (если нужен календарь/контакты): должен быть установлен и настроен
     на профиль по умолчанию, JARVIS обращается к нему через COM.

 Запуск (откройте новое окно PowerShell, чтобы подхватился PATH):
   jarvis              — голосовой режим в терминале (wake word «Hey Jarvis», Ctrl+B — говорить)
   jarvis hud          — открыть голографический HUD в браузере (http://127.0.0.1:8765)
   jarvis gateway      — Telegram/Discord/WhatsApp + API для HUD
   jarvis status       — состояние всех компонентов
   jarvis doctor --fix — если что-то не работает: проверит и починит
   jarvis vault open   — папка %USERPROFILE%\JARVIS: кладите файлы и проекты, JARVIS их читает
   jarvis app open     — значок в системном трее

 Документация: $JarvisSrc\docs\  (README.md -> начните с него)
══════════════════════════════════════════════════════════════════════
"@
