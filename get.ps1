#Requires -Version 5.1
<#
  JARVIS — установка одной командой (Windows):

      iwr -useb https://raw.githubusercontent.com/debug999-cyber/jarvis-hermes/main/get.ps1 | iex

  Что делает: скачивает последний стабильный релиз в %USERPROFILE%\Downloads\jarvis-hermes
  (git clone, если git есть, иначе zip релиза), затем запускает обычный install.ps1 —
  интерактивно, с вопросами.

  Переменные окружения:
    JARVIS_REPO=owner/name          другой репозиторий
    JARVIS_CHANNEL=main             свежий main вместо релиза
    JARVIS_DIR=C:\path              куда положить исходники
    JARVIS_INSTALL_ARGS="-Yes -NoVoice"   флаги install.ps1
#>

$ErrorActionPreference = "Stop"

$Repo = if ($env:JARVIS_REPO) { $env:JARVIS_REPO } else { "debug999-cyber/jarvis-hermes" }
$Channel = if ($env:JARVIS_CHANNEL) { $env:JARVIS_CHANNEL } else { "stable" }
$Dir = if ($env:JARVIS_DIR) { $env:JARVIS_DIR } else { Join-Path $env:USERPROFILE "Downloads\jarvis-hermes" }
$ExtraArgs = if ($env:JARVIS_INSTALL_ARGS) { $env:JARVIS_INSTALL_ARGS -split "\s+" } else { @() }

function Say([string]$msg) { Write-Host "▸ $msg" -ForegroundColor Cyan }
function Ok([string]$msg) { Write-Host "  ✔ $msg" -ForegroundColor Green }
function Fail([string]$msg) { Write-Host "✖ $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "   J.A.R.V.I.S.  установщик · $Repo · канал $Channel" -ForegroundColor Cyan
Write-Host ""

function Get-LatestTag {
    try {
        $r = Invoke-RestMethod -UseBasicParsing -Uri "https://api.github.com/repos/$Repo/releases/latest"
        return $r.tag_name
    } catch { return $null }
}

Say "Скачиваю JARVIS в $Dir"
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $Dir ".git")) {
        git -C $Dir fetch -q --tags origin
    } else {
        Remove-Item -Recurse -Force $Dir -ErrorAction SilentlyContinue
        git clone -q "https://github.com/$Repo.git" $Dir
    }
    if ($Channel -eq "stable") {
        $tag = Get-LatestTag
        if ($tag) {
            try { git -C $Dir checkout -q $tag } catch { git -C $Dir checkout -q main }
            Ok "версия $tag"
        } else {
            git -C $Dir checkout -q main; git -C $Dir pull -q --ff-only origin main
            Ok "релизов пока нет — беру main"
        }
    } else {
        git -C $Dir checkout -q main; git -C $Dir pull -q --ff-only origin main
        $sha = (git -C $Dir rev-parse --short HEAD)
        Ok "канал main ($sha)"
    }
} else {
    $tag = Get-LatestTag
    if (-not $tag) { Fail "не удалось узнать последний релиз $Repo (нет сети?)" }
    $tmpZip = Join-Path $env:TEMP "jarvis-hermes-$tag.zip"
    $ver = $tag.TrimStart("v")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/releases/download/$tag/jarvis-hermes-$ver.zip" -OutFile $tmpZip
    } catch { Fail "не скачался релиз $tag" }
    Remove-Item -Recurse -Force $Dir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    Expand-Archive -Path $tmpZip -DestinationPath $Dir -Force
    Remove-Item $tmpZip -ErrorAction SilentlyContinue
    Ok "версия $tag (zip)"
}

if (-not (Test-Path (Join-Path $Dir "install.ps1"))) { Fail "в $Dir нет install.ps1 — скачивание не удалось" }

Say "Запускаю установщик (он спросит про модель, голос, автозапуск)"
Write-Host ""
Push-Location $Dir
try {
    & (Join-Path $Dir "install.ps1") @ExtraArgs
} finally {
    Pop-Location
}
