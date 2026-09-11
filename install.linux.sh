#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  J.A.R.V.I.S. on Hermes Agent — установщик для Linux (X11/Wayland, native)
#
#  Что делает (идемпотентно — можно запускать повторно):
#   1. Определяет дистрибутив/пакетный менеджер (apt/dnf/pacman/zypper) и ставит
#      системные зависимости (portaudio, ffmpeg, xdotool/wmctrl, xclip/wl-clipboard,
#      playerctl, brightnessctl, espeak-ng, notify-send…) — best effort, не критично.
#   2. Устанавливает Hermes Agent (официальный install.sh), если его ещё нет.
#   3. Ставит voice extras: faster-whisper, edge-tts, openWakeWord.
#   4. Копирует плагины jarvis-core / jarvis-linux / jarvis-brain в $HERMES_HOME/plugins.
#   5. Ставит SOUL.md (личность), навыки, хук boot, cron-задачи.
#   6. Аккуратно вливает config.jarvis.linux.yaml в $HERMES_HOME/config.yaml.
#   7. Включает OpenAI-совместимый API (порт 8642) для HUD.
#   8. Устанавливает команду `jarvis` и (по желанию) автозапуск через systemd --user.
#   9. Запускает `hermes doctor` и печатает следующие шаги.
#
#  Флаги:  --no-systemd-user  --no-voice  --no-system-packages  --no-cron  --yes  --hermes-home DIR
#  Переменные (для updater): JARVIS_QUIET=1  JARVIS_COMMIT=sha  JARVIS_CHANNEL=stable|main  JARVIS_AUTO_UPDATE=off|check|auto
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ─── параметры ────────────────────────────────────────────────────────────
JARVIS_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="$HERMES_HOME/hermes-agent"
JARVIS_HOME="$HERMES_HOME/jarvis"
BIN_DIR="$HOME/.local/bin"
INSTALL_SYSTEMD=1; INSTALL_VOICE=1; INSTALL_SYSTEM_PKGS=1; INSTALL_CRON=1; ASSUME_YES=0
JARVIS_VERSION="$(cat "$JARVIS_SRC/VERSION" 2>/dev/null || echo 0.0.0)"
JARVIS_REPO="${JARVIS_REPO:-Ayazbog11/hermes-jarvis-all}"

for arg in "$@"; do
  case "$arg" in
    --no-systemd-user) INSTALL_SYSTEMD=0 ;;
    --no-voice)         INSTALL_VOICE=0 ;;
    --no-system-packages|--no-brew-tools|--no-launchd) INSTALL_SYSTEM_PKGS=0 ;;
    --no-cron)           INSTALL_CRON=0 ;;
    --yes|-y)            ASSUME_YES=1 ;;
    --hermes-home=*)     HERMES_HOME="${arg#*=}"; HERMES_REPO="$HERMES_HOME/hermes-agent"; JARVIS_HOME="$HERMES_HOME/jarvis" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  esac
done

# ─── оформление ───────────────────────────────────────────────────────────
C0='\033[0m'; CB='\033[1;36m'; CG='\033[1;32m'; CY='\033[1;33m'; CR='\033[1;31m'; CD='\033[2m'
step(){ printf "\n${CB}▶ %s${C0}\n" "$*"; }
ok(){   printf "${CG}  ✔ %s${C0}\n" "$*"; }
warn(){ printf "${CY}  ⚠ %s${C0}\n" "$*"; }
die(){  printf "${CR}  ✖ %s${C0}\n" "$*"; exit 1; }
ask(){
  [[ $ASSUME_YES -eq 1 ]] && return 0
  read -r -p "  $1 [Y/n] " a; [[ -z "$a" || "$a" =~ ^[YyДд] ]]
}

cat <<'BANNER'

     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
        on Hermes Agent  ·  Linux installer
BANNER

# ─── 1. пререквизиты ──────────────────────────────────────────────────────
step "Проверка системы"
[[ "$(uname -s)" == "Linux" ]] || die "Этот установщик только для Linux. Для macOS используйте install.sh, для Windows — install.ps1."
ARCH="$(uname -m)"
DISTRO="$( . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || echo "неизвестный дистрибутив")"
ok "$DISTRO · $ARCH · $([[ -n "${WAYLAND_DISPLAY:-}" ]] && echo Wayland || echo X11)"

PKG_MGR=""
for m in apt dnf yum pacman zypper apk; do
  command -v "$m" >/dev/null 2>&1 && { PKG_MGR="$m"; break; }
done
[[ -n "$PKG_MGR" ]] && ok "Пакетный менеджер: $PKG_MGR" || warn "Пакетный менеджер не распознан — системные зависимости придётся ставить вручную"

pkg_install(){
  # pkg_install pkg1 pkg2 …  — best effort, ошибки не прерывают установку
  [[ -z "$PKG_MGR" ]] && return 1
  case "$PKG_MGR" in
    apt)     sudo apt-get update -qq >/dev/null 2>&1 || true; sudo apt-get install -y "$@" >/dev/null 2>&1 ;;
    dnf)     sudo dnf install -y "$@" >/dev/null 2>&1 ;;
    yum)     sudo yum install -y "$@" >/dev/null 2>&1 ;;
    pacman)  sudo pacman -Sy --noconfirm "$@" >/dev/null 2>&1 ;;
    zypper)  sudo zypper install -y "$@" >/dev/null 2>&1 ;;
    apk)     sudo apk add "$@" >/dev/null 2>&1 ;;
  esac
}

if [[ $INSTALL_SYSTEM_PKGS -eq 1 && -n "$PKG_MGR" ]]; then
  step "Системные зависимости ($PKG_MGR)"
  # имена пакетов немного различаются между дистрибутивами; берём apt-стиль как основной набор
  case "$PKG_MGR" in
    apt)    PKGS=(git portaudio19-dev ffmpeg libopus0 jq curl wmctrl xdotool xclip wl-clipboard playerctl \
                  brightnessctl libnotify-bin scrot grim gnome-screenshot upower bluez network-manager) ;;
    dnf|yum) PKGS=(git portaudio ffmpeg opus jq curl wmctrl xdotool xclip wl-clipboard playerctl \
                  brightnessctl libnotify scrot grim gnome-screenshot upower bluez NetworkManager) ;;
    pacman) PKGS=(git portaudio ffmpeg opus jq curl wmctrl xdotool xclip wl-clipboard playerctl \
                  brightnessctl libnotify scrot grim gnome-screenshot upower bluez networkmanager) ;;
    *)      PKGS=(git portaudio ffmpeg opus jq curl wmctrl xdotool xclip playerctl brightnessctl) ;;
  esac
  [[ $INSTALL_VOICE -eq 1 ]] && PKGS+=(espeak-ng)
  printf "  ${CD}… устанавливаю системные пакеты (может спросить sudo-пароль)${C0}\n"
  if pkg_install "${PKGS[@]}"; then ok "системные пакеты установлены (best effort)"; else warn "часть пакетов не установилась — не критично, доустановите вручную по необходимости"; fi
else
  warn "Установка системных пакетов пропущена (--no-system-packages или пакетный менеджер не найден)"
fi

# ─── 2. Hermes Agent ──────────────────────────────────────────────────────
step "Hermes Agent"
if command -v hermes >/dev/null 2>&1 || [[ -x "$BIN_DIR/hermes" ]]; then
  ok "уже установлен: $(command -v hermes || echo "$BIN_DIR/hermes")"
else
  echo "  Устанавливаю Hermes Agent официальным скриптом (uv + Python 3.11 + репозиторий)…"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --skip-computer-use || \
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
fi
export PATH="$BIN_DIR:$PATH"
command -v hermes >/dev/null 2>&1 || die "Команда hermes недоступна. Откройте новый терминал (или source ~/.bashrc) и запустите install.linux.sh снова."
[[ -d "$HERMES_REPO" ]] || die "Не найден репозиторий Hermes в $HERMES_REPO"
ok "hermes $(hermes --version 2>/dev/null | head -1 || echo '')"

VENV_PY="$HERMES_REPO/venv/bin/python"
[[ -x "$VENV_PY" ]] || VENV_PY="$(command -v python3)"

# ─── 3. голосовые extras ──────────────────────────────────────────────────
if [[ $INSTALL_VOICE -eq 1 ]]; then
  step "Голос: faster-whisper (STT), Edge TTS, openWakeWord (wake word)"
  ( cd "$HERMES_REPO" && {
      if command -v uv >/dev/null 2>&1; then
        export VIRTUAL_ENV="$HERMES_REPO/venv"
        uv pip install -q -e ".[voice,wake]" 2>/dev/null || uv pip install -q -e ".[voice]" || true
        uv pip install -q faster-whisper edge-tts sounddevice numpy 2>/dev/null || true
      else
        "$VENV_PY" -m pip install -q -e ".[voice]" || true
        "$VENV_PY" -m pip install -q faster-whisper edge-tts sounddevice numpy || true
      fi
  } ) && ok "voice extras установлены" || warn "часть голосовых пакетов не установилась — см. docs/TROUBLESHOOTING.md"
fi

# ─── 4. плагины ───────────────────────────────────────────────────────────
step "Плагины JARVIS → $HERMES_HOME/plugins"
mkdir -p "$HERMES_HOME/plugins"
for plug in jarvis-core jarvis-linux jarvis-brain; do
  [[ -f "$JARVIS_SRC/plugins/$plug/plugin.yaml" ]] || die "в архиве нет плагина $plug — скачайте проект заново"
done
for plug in jarvis-core jarvis-linux jarvis-brain; do
  rm -rf "$HERMES_HOME/plugins/$plug"
  cp -R "$JARVIS_SRC/plugins/$plug" "$HERMES_HOME/plugins/$plug"
  ok "$plug"
done

# ─── 5. личность, навыки, хуки, HUD ───────────────────────────────────────
step "Личность (SOUL.md), навыки, хуки, HUD"
if [[ -f "$HERMES_HOME/SOUL.md" ]] && ! grep -q "J.A.R.V.I.S" "$HERMES_HOME/SOUL.md"; then
  cp "$HERMES_HOME/SOUL.md" "$HERMES_HOME/SOUL.md.bak.$(date +%s)"; warn "ваш прежний SOUL.md сохранён как SOUL.md.bak.*"
fi
cp "$JARVIS_SRC/config/SOUL.md" "$HERMES_HOME/SOUL.md"; ok "SOUL.md"

mkdir -p "$HERMES_HOME/skills/jarvis"
cp -R "$JARVIS_SRC/skills/." "$HERMES_HOME/skills/jarvis/"; ok "skills/jarvis/*"

mkdir -p "$HERMES_HOME/hooks"
rm -rf "$HERMES_HOME/hooks/jarvis-boot"; cp -R "$JARVIS_SRC/hooks/jarvis-boot" "$HERMES_HOME/hooks/"; ok "hooks/jarvis-boot"
[[ -f "$HERMES_HOME/BOOT.md" ]] || cp "$JARVIS_SRC/config/BOOT.md" "$HERMES_HOME/BOOT.md"

mkdir -p "$HERMES_HOME/skill-bundles"
cp "$JARVIS_SRC/skill-bundles/jarvis.linux.yaml" "$HERMES_HOME/skill-bundles/jarvis.yaml"; ok "skill-bundles/jarvis.yaml  (/jarvis в чате)"
mkdir -p "$JARVIS_HOME"; cp "$JARVIS_SRC/config/.env.example" "$JARVIS_HOME/env.example"

mkdir -p "$JARVIS_HOME"
rm -rf "$JARVIS_HOME/hud"; cp -R "$JARVIS_SRC/hud" "$JARVIS_HOME/hud"
rm -rf "$JARVIS_HOME/tray"; mkdir -p "$JARVIS_HOME/tray"; cp -R "$JARVIS_SRC/app-linux/." "$JARVIS_HOME/tray/"
cp "$JARVIS_SRC/config/config.jarvis.linux.yaml" "$JARVIS_HOME/config.jarvis.yaml"
cp "$JARVIS_SRC/scripts/merge_config.py" "$JARVIS_HOME/"
cp "$JARVIS_SRC/scripts/setup_cron.sh" "$JARVIS_HOME/"
cp "$JARVIS_SRC/scripts/selftest.py" "$JARVIS_HOME/"
cp "$JARVIS_SRC/scripts/update.py" "$JARVIS_HOME/"
cp "$JARVIS_SRC/scripts/doctor.py" "$JARVIS_HOME/"
cp "$JARVIS_SRC/scripts/make_shortcuts.py" "$JARVIS_HOME/" 2>/dev/null || true
cp "$JARVIS_SRC/scripts/calendar_cli.py" "$JARVIS_HOME/"
cp "$JARVIS_SRC/scripts/ollama_local.py" "$JARVIS_HOME/"
cp "$JARVIS_SRC/scripts/usage_report.py" "$JARVIS_HOME/"
cp "$JARVIS_SRC/scripts/model_switch.py" "$JARVIS_HOME/"
cp "$JARVIS_SRC/VERSION" "$JARVIS_HOME/VERSION"
[[ "$HERMES_HOME" == "$HOME/.hermes" ]] && rm -f "$HOME/.jarvis-home" || echo "$HERMES_HOME" > "$HOME/.jarvis-home"
cp "$JARVIS_SRC/config/HEARTBEAT.md" "$JARVIS_HOME/" 2>/dev/null || true
ok "HUD → $JARVIS_HOME/hud"

# ─── 6. конфигурация ──────────────────────────────────────────────────────
step "Конфигурация $HERMES_HOME/config.yaml"
[[ -f "$HERMES_HOME/config.yaml" ]] || hermes config >/dev/null 2>&1 || true
[[ -f "$HERMES_HOME/config.yaml" ]] || echo "{}" > "$HERMES_HOME/config.yaml"
cp "$HERMES_HOME/config.yaml" "$HERMES_HOME/config.yaml.bak.jarvis"
"$VENV_PY" "$JARVIS_SRC/scripts/merge_config.py" "$JARVIS_SRC/config/config.jarvis.linux.yaml" "$HERMES_HOME/config.yaml" \
  && ok "ключи JARVIS добавлены (бэкап: config.yaml.bak.jarvis)" || warn "merge не удался — примените config/config.jarvis.linux.yaml вручную"

# ─── 7. API-сервер для HUD ────────────────────────────────────────────────
step "OpenAI-совместимый API Hermes (для HUD)"
ENV_FILE="$HERMES_HOME/.env"; touch "$ENV_FILE"
env_has(){ grep -Eq "^$1=[^[:space:]#]+" "$ENV_FILE"; }
env_has API_SERVER_ENABLED || { sed -i '/^API_SERVER_ENABLED=/d' "$ENV_FILE"; echo "API_SERVER_ENABLED=true" >> "$ENV_FILE"; }
if ! env_has API_SERVER_KEY; then
  sed -i '/^API_SERVER_KEY=/d' "$ENV_FILE"
  KEY="$(openssl rand -hex 24 2>/dev/null || "$VENV_PY" -c 'import secrets;print(secrets.token_hex(24))')"
  echo "API_SERVER_KEY=$KEY" >> "$ENV_FILE"; ok "сгенерирован API_SERVER_KEY"
else ok "API_SERVER_KEY уже задан"; fi
env_has API_SERVER_HOST || { sed -i '/^API_SERVER_HOST=/d' "$ENV_FILE"; echo "API_SERVER_HOST=127.0.0.1" >> "$ENV_FILE"; }
chmod 600 "$ENV_FILE"

# ─── 8. команда jarvis + systemd --user ───────────────────────────────────
step "Команда \`jarvis\`"
mkdir -p "$BIN_DIR"
sed -e "s#__HERMES_HOME__#$HERMES_HOME#g" -e "s#__PYTHON__#$VENV_PY#g" "$JARVIS_SRC/bin/jarvis" > "$BIN_DIR/jarvis"
chmod +x "$BIN_DIR/jarvis"; ok "$BIN_DIR/jarvis"
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
  [[ -f "$rc" ]] && ! grep -q '.local/bin' "$rc" && echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc" || true
done

"$VENV_PY" - "$JARVIS_HOME/install.json" "$JARVIS_VERSION" "${JARVIS_COMMIT:-}" "$JARVIS_REPO" "${JARVIS_CHANNEL:-}" "${JARVIS_AUTO_UPDATE:-}" <<'PY'
import json, sys, datetime, pathlib
p, ver, commit, repo, channel, auto = pathlib.Path(sys.argv[1]), *sys.argv[2:7]
old = {}
try: old = json.loads(p.read_text())
except Exception: pass
data = {**old, "version": ver, "commit": commit or old.get("commit", ""), "repo": repo,
        "channel": channel or old.get("channel", "stable"), "auto_update": auto or old.get("auto_update", "auto"),
        "installed_at": datetime.datetime.now().replace(microsecond=0).isoformat()}
p.write_text(json.dumps(data, ensure_ascii=False, indent=2))
PY
ok "install.json: версия $JARVIS_VERSION"

if [[ $INSTALL_SYSTEMD -eq 1 ]] && command -v systemctl >/dev/null 2>&1 && ask "Настроить автозапуск HUD и gateway при входе в систему (systemd --user)?"; then
  UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR" "$HERMES_HOME/logs"
  for unit in jarvis-hud.service jarvis-gateway.service jarvis-updater.service jarvis-updater.timer; do
    sed -e "s#__HERMES_HOME__#$HERMES_HOME#g" -e "s#__PYTHON__#$VENV_PY#g" -e "s#__HERMES_BIN__#$(command -v hermes)#g" \
        -e "s#__HOME__#$HOME#g" "$JARVIS_SRC/config/systemd/$unit" > "$UNIT_DIR/$unit"
  done
  systemctl --user daemon-reload
  systemctl --user enable --now jarvis-hud.service jarvis-gateway.service jarvis-updater.timer \
    && ok "systemd --user: юниты включены" || warn "не удалось включить юниты — попробуйте вручную: systemctl --user enable --now jarvis-hud jarvis-gateway jarvis-updater.timer"
  # loginctl linger — чтобы юниты стартовали даже без активной GUI-сессии (headless/сервер)
  loginctl enable-linger "$USER" >/dev/null 2>&1 || true
fi

# ─── 8b. значок в трее (автозапуск через .desktop) ────────────────────────
if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]] && ask "Поставить значок JARVIS в системный трей (запуск при входе в систему)?"; then
  step "Значок в трее"
  ( cd "$HERMES_REPO" && {
      if command -v uv >/dev/null 2>&1; then
        export VIRTUAL_ENV="$HERMES_REPO/venv"; uv pip install -q pystray pillow 2>/dev/null || true
      else
        "$VENV_PY" -m pip install -q pystray pillow || true
      fi
  } )
  AUTOSTART_DIR="$HOME/.config/autostart"; mkdir -p "$AUTOSTART_DIR"
  sed -e "s#__HERMES_HOME__#$HERMES_HOME#g" -e "s#__PYTHON__#$VENV_PY#g" \
      "$JARVIS_SRC/config/jarvis-tray.desktop" > "$AUTOSTART_DIR/jarvis-tray.desktop"
  ok "автозапуск: $AUTOSTART_DIR/jarvis-tray.desktop  (на GNOME нужно расширение AppIndicator)"
  [[ "${JARVIS_QUIET:-0}" == "1" ]] || nohup "$VENV_PY" "$JARVIS_HOME/tray/jarvis_tray.py" >/dev/null 2>&1 &
fi

# ─── 9. cron-задачи JARVIS ────────────────────────────────────────────────
step "Фоновые задачи (утренний брифинг, контроль батареи)"
if [[ $INSTALL_CRON -eq 1 ]] && ask "Создать cron-задачи JARVIS (брифинг 08:00, вечерний итог 21:00, ночная ревизия 03:30, heartbeat)?"; then
  bash "$JARVIS_SRC/scripts/setup_cron.sh" || warn "cron не настроен — можно позже: bash ~/.hermes/jarvis/setup_cron.sh"
fi

if [[ "${JARVIS_QUIET:-0}" == "1" ]]; then echo "JARVIS $JARVIS_VERSION установлен (тихий режим updater)"; exit 0; fi

# ─── 10. модель ───────────────────────────────────────────────────────────
step "Провайдер LLM"
if hermes config get model >/dev/null 2>&1 && [[ -n "$(hermes config get model 2>/dev/null | tr -d '[:space:]')" ]]; then
  ok "модель: $(hermes config get model 2>/dev/null)"
  printf "  ${CD}… проверяю, что модель отвечает${C0}\n"
  PING="$(timeout 90 hermes chat -q 'Ответь одним словом: ok' 2>&1 | tail -c 400 || true)"
  if [[ -z "$PING" ]] || echo "$PING" | grep -qiE "error code|http [45][0-9][0-9]|traceback|\b(401|403|405|429)\b"; then
    warn "модель настроена, но НЕ отвечает: ${PING:-пустой ответ}"
    if [[ $ASSUME_YES -eq 0 ]] && ask "Открыть мастер выбора модели сейчас (рекомендую OpenRouter или Ollama)?"; then hermes model || true; fi
  else ok "модель отвечает"; fi
else
  warn "Модель не настроена. Сейчас откроется мастер — выберите провайдера (OpenRouter / Anthropic / OpenAI / Nous Portal / Ollama)."
  [[ $ASSUME_YES -eq 1 ]] || hermes model || true
fi

# ─── 11. доктор ───────────────────────────────────────────────────────────
step "Диагностика"
if ! hermes plugins list 2>/dev/null | grep -qi jarvis-core; then
  hermes plugins enable jarvis-core jarvis-linux jarvis-brain >/dev/null 2>&1 && ok "плагины включены" \
    || warn "плагины не отображаются — выполните: hermes plugins enable jarvis-core jarvis-linux jarvis-brain"
fi
hermes plugins list 2>/dev/null | grep -i jarvis || true
"$VENV_PY" "$JARVIS_HOME/doctor.py" --quick --fix 2>/dev/null || true

# ─── итог ─────────────────────────────────────────────────────────────────
cat <<EOF

${CG}══════════════════════════════════════════════════════════════════════${C0}
${CG} J.A.R.V.I.S. установлен.${C0}

 Полезно доустановить (если не встало автоматически) в зависимости от окружения:
   X11:      xdotool, wmctrl, xclip, scrot                     (управление окнами, ввод, буфер, скриншоты)
   Wayland:  grim, slurp, wl-clipboard, ydotool+ydotoold        (аналоги того же самого)
   Общее:    playerctl, brightnessctl, upower, bluez, NetworkManager, libnotify-bin, espeak-ng

 Запуск:
   ${CB}jarvis${C0}            — голосовой режим в терминале (wake word «Hey Jarvis», Ctrl+B — говорить)
   ${CB}jarvis hud${C0}        — открыть голографический HUD в браузере (http://127.0.0.1:8765)
   ${CB}jarvis gateway${C0}    — Telegram/Discord/WhatsApp + API для HUD
   ${CB}jarvis status${C0}     — состояние всех компонентов
   ${CB}jarvis doctor --fix${C0} — если что-то не работает: проверит и починит
   ${CB}jarvis vault open${C0} — папка ~/JARVIS: кладите файлы и проекты, JARVIS их читает

 Документация: $JARVIS_SRC/docs/  (README.md → начните с него)
${CG}══════════════════════════════════════════════════════════════════════${C0}
EOF
