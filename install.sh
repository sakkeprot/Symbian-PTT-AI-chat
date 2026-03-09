#!/usr/bin/env bash
# =============================================================================
# PoC AI Proxy — Install Script
# Tested on Ubuntu 22.04 / 24.04 (AWS EC2 or any VPS)
# Run as: sudo bash install.sh   (from inside the cloned repo)
# =============================================================================

# NO set -e — we handle errors ourselves and keep going where safe

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$SCRIPT_DIR"

# Detect the real user behind sudo
if [[ -n "$SUDO_USER" ]]; then
  SERVICE_USER="$SUDO_USER"
  SERVICE_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
  SERVICE_USER="$(whoami)"
  SERVICE_HOME="$HOME"
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

WARNINGS=()

info()    { echo -e "${GREEN}  ✓${NC}  $*"; }
warn()    { echo -e "${YELLOW}  ⚠${NC}  $*"; WARNINGS+=("$*"); }
fatal()   { echo -e "\n${RED}${BOLD}FATAL: $*${NC}\n"; exit 1; }
section() {
  echo ""
  echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
  echo -e "${GREEN}${BOLD}  $*${NC}"
  echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
  echo ""
}
ask() { echo -e "${CYAN}${BOLD}$*${NC}"; }

# =============================================================================
# Sanity checks
# =============================================================================
[[ $EUID -ne 0 ]] && fatal "Please run as root:  sudo bash install.sh"
[[ ! -f "$REPO_DIR/poc_proxy.py" ]] && fatal "Run this script from inside the cloned repo directory."

INSTALL_LOG="$REPO_DIR/install.log"
: > "$INSTALL_LOG"
echo "Install log — $(date)" >> "$INSTALL_LOG"
echo "REPO_DIR=$REPO_DIR  USER=$SERVICE_USER" >> "$INSTALL_LOG"

# =============================================================================
# Welcome
# =============================================================================
clear
echo -e "${BOLD}"
echo "  ██████╗  ██████╗  ██████╗     █████╗ ██╗"
echo "  ██╔══██╗██╔═══██╗██╔════╝    ██╔══██╗██║"
echo "  ██████╔╝██║   ██║██║         ███████║██║"
echo "  ██╔═══╝ ██║   ██║██║         ██╔══██║██║"
echo "  ██║     ╚██████╔╝╚██████╗    ██║  ██║██║"
echo "  ╚═╝      ╚═════╝  ╚═════╝    ╚═╝  ╚═╝╚═╝"
echo -e "${NC}"
echo -e "${BOLD}  PoC AI Proxy — Installer${NC}"
echo "  Turns any Nokia PTT phone into an AI walkie-talkie"
echo ""
echo -e "  Installing into: ${BOLD}$REPO_DIR${NC}"
echo -e "  Running as user: ${BOLD}$SERVICE_USER${NC}"
echo -e "  Full log at:     ${BOLD}$INSTALL_LOG${NC}"
echo ""
read -rp "  Press ENTER to begin..." _

# =============================================================================
# STEP 1 — Language
# =============================================================================
section "Step 1 of 4 — Language"
echo "  Choose the language for speech recognition, TTS and AI replies:"
echo ""
echo "    1)  Dutch    (nl-BE-ArnaudNeural)"
echo "    2)  English  (en-US-GuyNeural)"
echo "    3)  French   (fr-FR-HenriNeural)"
echo "    4)  German   (de-DE-KillianNeural)"
echo "    5)  Spanish  (es-ES-AlvaroNeural)"
echo ""
while true; do
  ask "  Enter number [1-5]:"
  read -rp "  > " LANG_CHOICE
  case "$LANG_CHOICE" in
    1) LANGUAGE="dutch";   break ;;
    2) LANGUAGE="english"; break ;;
    3) LANGUAGE="french";  break ;;
    4) LANGUAGE="german";  break ;;
    5) LANGUAGE="spanish"; break ;;
    *) echo -e "  ${RED}Please enter a number between 1 and 5.${NC}" ;;
  esac
done
info "Language: $LANGUAGE"

# =============================================================================
# STEP 2 — DeepSeek API key
# =============================================================================
section "Step 2 of 4 — DeepSeek API key  (AI replies)"
echo "  DeepSeek generates the spoken replies."
echo ""
echo -e "  ${BOLD}How to get your key:${NC}"
echo "    1. Go to  https://platform.deepseek.com"
echo "    2. Sign up and log in"
echo "    3. Click 'API Keys' → 'Create new key'"
echo "    4. Your key looks like:  sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
echo ""
echo -e "  ${YELLOW}${BOLD}💳  You need to top up your account before it will work."
echo -e "  \$1–\$2 is enough for months of use (fractions of a cent per call).${NC}"
echo ""
while true; do
  ask "  Paste your DeepSeek API key  (or press ENTER to skip and set later):"
  read -rp "  > " DEEPSEEK_API_KEY
  if   [[ -z "$DEEPSEEK_API_KEY" ]];       then warn "DeepSeek key skipped — set it in config.py before starting"; break
  elif [[ "$DEEPSEEK_API_KEY" == sk-* ]];  then info "DeepSeek key accepted"; break
  else echo -e "  ${RED}DeepSeek keys start with 'sk-' — try again or press ENTER to skip.${NC}"
  fi
done

# =============================================================================
# STEP 3 — Groq API key
# =============================================================================
section "Step 3 of 4 — Groq API key  (Speech recognition)"
echo "  Groq runs Whisper large-v3. Free to sign up, no credit card needed."
echo ""
echo -e "  ${BOLD}How to get your key:${NC}"
echo "    1. Go to  https://console.groq.com"
echo "    2. Sign up for free and log in"
echo "    3. Click 'API Keys' → 'Create API Key'"
echo "    4. Your key looks like:  gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
echo ""
echo -e "  ${YELLOW}If skipped, speech recognition falls back to local whisper.cpp.${NC}"
echo ""
while true; do
  ask "  Paste your Groq API key  (or press ENTER to skip):"
  read -rp "  > " GROQ_API_KEY
  if   [[ -z "$GROQ_API_KEY" ]];          then warn "Groq key skipped — local whisper.cpp will be used as fallback"; break
  elif [[ "$GROQ_API_KEY" == gsk_* ]];    then info "Groq key accepted"; break
  else echo -e "  ${RED}Groq keys start with 'gsk_' — try again or press ENTER to skip.${NC}"
  fi
done

# =============================================================================
# STEP 4 — Confirm
# =============================================================================
section "Step 4 of 4 — Confirm & install"
echo "  Settings summary:"
echo ""
echo -e "    Install dir : ${BOLD}$REPO_DIR${NC}"
echo -e "    Language    : ${BOLD}$LANGUAGE${NC}"
[[ -n "$DEEPSEEK_API_KEY" ]] \
  && echo -e "    DeepSeek    : ${GREEN}✓ set  (${DEEPSEEK_API_KEY:0:8}...)${NC}" \
  || echo -e "    DeepSeek    : ${YELLOW}⚠ not set${NC}"
[[ -n "$GROQ_API_KEY" ]] \
  && echo -e "    Groq STT    : ${GREEN}✓ set  (${GROQ_API_KEY:0:8}...)${NC}" \
  || echo -e "    Groq STT    : ${YELLOW}⚠ not set — local whisper fallback${NC}"
echo ""
ask "  Proceed? [Y/n]"
read -rp "  > " CONFIRM
[[ "$CONFIRM" =~ ^[Nn] ]] && { echo "Aborted."; exit 0; }

# =============================================================================
# SYSTEM PACKAGES
# =============================================================================
section "Installing system packages"

echo "  → apt-get update"
apt-get update -qq >> "$INSTALL_LOG" 2>&1 \
  || warn "apt-get update failed — package installs may fail"

echo "  → Installing core packages"
apt-get install -y \
  python3 python3-pip python3-venv \
  ffmpeg espeak-ng asterisk \
  git cmake build-essential \
  libssl-dev libsrtp2-dev \
  curl wget >> "$INSTALL_LOG" 2>&1 \
  || warn "Some packages failed to install — check $INSTALL_LOG"

echo "  → Installing AMR codec libraries"
apt-get install -y \
  nasm yasm libmp3lame-dev libopus-dev \
  libvo-amrwbenc-dev libopencore-amrnb-dev libopencore-amrwb-dev \
  >> "$INSTALL_LOG" 2>&1 \
  || warn "AMR codec libraries unavailable in apt — ffmpeg source build may fail"

# =============================================================================
# FFMPEG — build from source if AMR-NB encoder is missing
# The Ubuntu apt ffmpeg ships decode-only; we need the encoder too.
# Key fix: extract as root, then chown to current user so configure can write
# its temp files, then sudo only for make install and ldconfig.
# =============================================================================
if ffmpeg -codecs 2>/dev/null | grep amrnb | grep -q libopencore_amrnb; then
  info "ffmpeg already has AMR-NB encoder support"
else
  echo ""
  echo -e "  ${YELLOW}System ffmpeg has AMR-NB decode only — building encoder from source.${NC}"
  echo -e "  ${YELLOW}This takes 5–10 minutes. Grab a coffee.${NC}"
  echo ""

  FFMPEG_VERSION="6.1"
  FFMPEG_DIR="/tmp/ffmpeg-${FFMPEG_VERSION}"
  FFMPEG_TAR="/tmp/ffmpeg-${FFMPEG_VERSION}.tar.gz"
  BUILD_OK=true

  # Clean up any previous failed attempt
  echo "  → Cleaning up any previous ffmpeg build"
  rm -rf "$FFMPEG_DIR" "$FFMPEG_TAR"

  echo "  → Downloading ffmpeg ${FFMPEG_VERSION} source"
  wget -q "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.gz" \
    -O "$FFMPEG_TAR" >> "$INSTALL_LOG" 2>&1 \
    || { warn "ffmpeg download failed — check internet connectivity"; BUILD_OK=false; }

  if [[ "$BUILD_OK" == true ]]; then
    echo "  → Extracting source"
    tar xf "$FFMPEG_TAR" -C /tmp >> "$INSTALL_LOG" 2>&1 \
      || { warn "ffmpeg extraction failed"; BUILD_OK=false; }
  fi

  if [[ "$BUILD_OK" == true ]]; then
    echo "  → Configuring ffmpeg"
    # Run configure directly as root — we are already root and this is simplest
    cd "$FFMPEG_DIR"
    ./configure \
      --enable-libopencore-amrnb \
      --enable-libopencore-amrwb \
      --enable-version3 --enable-gpl --enable-nonfree \
      --enable-libmp3lame --enable-libopus \
      --prefix=/usr/local \
      --disable-doc --disable-htmlpages \
      --disable-manpages --disable-podpages --disable-txtpages \
      >> "$INSTALL_LOG" 2>&1 \
      || { warn "ffmpeg configure failed — see $INSTALL_LOG"; BUILD_OK=false; }
  fi

  if [[ "$BUILD_OK" == true ]]; then
    echo "  → Compiling ffmpeg  (this is the slow part — ~5-10 min)"
    cd "$FFMPEG_DIR"
    make -j"$(nproc)" >> "$INSTALL_LOG" 2>&1 \
      || { warn "ffmpeg compile failed — see $INSTALL_LOG"; BUILD_OK=false; }
  fi

  if [[ "$BUILD_OK" == true ]]; then
    echo "  → Installing ffmpeg to /usr/local"
    cd "$FFMPEG_DIR"
    make install >> "$INSTALL_LOG" 2>&1 \
      || { warn "ffmpeg install failed — see $INSTALL_LOG"; BUILD_OK=false; }
    ldconfig >> "$INSTALL_LOG" 2>&1
  fi

  if [[ "$BUILD_OK" == true ]]; then
    # Verify encoder actually landed
    if /usr/local/bin/ffmpeg -codecs 2>/dev/null | grep amrnb | grep -q libopencore_amrnb; then
      info "ffmpeg built and installed with AMR-NB encoder"
    else
      warn "ffmpeg installed but AMR-NB encoder not detected — audio may still fail"
    fi
  else
    warn "ffmpeg source build failed — TTS audio will not work until fixed"
    warn "To retry manually:  sudo rm -rf /tmp/ffmpeg-6.1 && sudo bash install.sh"
  fi

  # Cleanup build dir to save disk space
  rm -rf "$FFMPEG_DIR" "$FFMPEG_TAR"
  cd "$REPO_DIR"
fi

# =============================================================================
# PYTHON DEPENDENCIES
# =============================================================================
section "Installing Python dependencies"

echo "  → pip3 install requests edge-tts"
if pip3 install --break-system-packages requests edge-tts >> "$INSTALL_LOG" 2>&1; then
  info "Python packages installed (--break-system-packages)"
elif pip3 install requests edge-tts >> "$INSTALL_LOG" 2>&1; then
  info "Python packages installed"
else
  warn "pip3 install failed — try manually: pip3 install requests edge-tts"
fi

# =============================================================================
# WHISPER.CPP
# =============================================================================
section "Building whisper.cpp  (local STT fallback)"
WHISPER_DIR="$REPO_DIR/whisper.cpp"

if [[ -f "$WHISPER_DIR/build/bin/whisper-cli" ]]; then
  info "whisper.cpp already built — skipping"
else
  WHISPER_OK=true

  # Remove incomplete clone if present
  if [[ -d "$WHISPER_DIR" ]] && [[ ! -f "$WHISPER_DIR/CMakeLists.txt" ]]; then
    echo "  → Removing incomplete whisper.cpp directory"
    rm -rf "$WHISPER_DIR"
  fi

  if [[ ! -d "$WHISPER_DIR" ]]; then
    echo "  → Cloning whisper.cpp"
    git clone \
      https://github.com/ggerganov/whisper.cpp.git "$WHISPER_DIR" \
      >> "$INSTALL_LOG" 2>&1 \
      || { warn "whisper.cpp clone failed — STT fallback unavailable"; WHISPER_OK=false; }
  fi

  if [[ "$WHISPER_OK" == true ]]; then
    echo "  → Building whisper.cpp"
    cd "$WHISPER_DIR"
    cmake -B build -DWHISPER_BUILD_EXAMPLES=ON >> "$INSTALL_LOG" 2>&1       && cmake --build build --config Release -j"$(nproc)" >> "$INSTALL_LOG" 2>&1       || { warn "whisper.cpp build failed — STT fallback unavailable"; WHISPER_OK=false; }
  fi

  if [[ "$WHISPER_OK" == true ]]; then
    echo "  → Downloading base model (~145 MB)"
    cd "$WHISPER_DIR"
    mkdir -p models
    bash models/download-ggml-model.sh base >> "$INSTALL_LOG" 2>&1       || warn "Model download failed — re-run: bash whisper.cpp/models/download-ggml-model.sh base"
  fi

  if [[ "$WHISPER_OK" == true ]] && [[ -f "$WHISPER_DIR/build/bin/whisper-cli" ]]; then
    # Fix ownership so service user owns the whisper dir
    chown -R "$SERVICE_USER:$SERVICE_USER" "$WHISPER_DIR" 2>/dev/null || true
    info "whisper.cpp ready at $WHISPER_DIR"
  else
    warn "whisper.cpp not fully built — Groq will handle STT if key is set"
  fi
fi

# Return to repo dir after potentially cd-ing elsewhere
cd "$REPO_DIR"

# =============================================================================
# ASTERISK
# =============================================================================
section "Configuring Asterisk"
ASTERISK_CONF_DIR="/etc/asterisk"

echo "  → Detecting public IP"
PUBLIC_IP=""
for url in https://api.ipify.org https://ifconfig.me https://icanhazip.com; do
  PUBLIC_IP=$(curl -s --max-time 5 "$url" 2>/dev/null | tr -d '[:space:]')
  [[ -n "$PUBLIC_IP" ]] && break
done
if [[ -z "$PUBLIC_IP" ]]; then
  warn "Could not auto-detect public IP — set MY_IP manually in config.py"
  PUBLIC_IP="YOUR_PUBLIC_IP"
else
  info "Public IP: $PUBLIC_IP"
fi

LOCAL_NET=$(ip route 2>/dev/null | awk '/^[0-9]/ && !/default/ {print $1}' | head -1)
[[ -z "$LOCAL_NET" ]] && LOCAL_NET="192.168.0.0/255.255.0.0"
info "Local subnet: $LOCAL_NET"

if [[ ! -f "$REPO_DIR/sip.conf" ]]; then
  warn "sip.conf not found in repo — Asterisk config NOT updated"
else
  # Back up existing config
  if [[ -f "$ASTERISK_CONF_DIR/sip.conf" ]]; then
    BACKUP="$ASTERISK_CONF_DIR/sip.conf.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$ASTERISK_CONF_DIR/sip.conf" "$BACKUP" \
      && info "Backed up old sip.conf → $BACKUP" \
      || warn "Could not back up old sip.conf"
  fi

  if cp "$REPO_DIR/sip.conf" "$ASTERISK_CONF_DIR/sip.conf"; then
    sed -i "s|YOUR_PUBLIC_IP|$PUBLIC_IP|g"          "$ASTERISK_CONF_DIR/sip.conf"
    sed -i "s|172.31.0.0/255.255.0.0|$LOCAL_NET|g"  "$ASTERISK_CONF_DIR/sip.conf"

    if grep -q "YOUR_PUBLIC_IP" "$ASTERISK_CONF_DIR/sip.conf"; then
      warn "IP substitution may have failed — check externaddr= in sip.conf manually"
    else
      info "sip.conf written  (externaddr=$PUBLIC_IP)"
    fi
  else
    warn "Failed to copy sip.conf — check permissions on $ASTERISK_CONF_DIR"
  fi
fi

EXTEN_CONF="$ASTERISK_CONF_DIR/extensions.conf"
if ! grep -q '\[default\]' "$EXTEN_CONF" 2>/dev/null; then
  cat > "$EXTEN_CONF" <<'EOF'
[default]
exten => _X.,1,Answer()
 same => n,Echo()
 same => n,Hangup()

[from-office]
exten => _X.,1,Answer()
 same => n,Echo()
 same => n,Hangup()
EOF
  info "Minimal extensions.conf written"
else
  info "extensions.conf already configured — leaving it alone"
fi

echo "  → Reloading Asterisk"
if systemctl is-active --quiet asterisk 2>/dev/null; then
  asterisk -rx 'module reload' >> "$INSTALL_LOG" 2>&1 \
    && info "Asterisk reloaded" \
    || { systemctl restart asterisk >> "$INSTALL_LOG" 2>&1 \
         && info "Asterisk restarted" \
         || warn "Asterisk restart failed — check: journalctl -u asterisk"; }
else
  systemctl enable asterisk >> "$INSTALL_LOG" 2>&1 || true
  systemctl start asterisk  >> "$INSTALL_LOG" 2>&1 \
    && info "Asterisk started" \
    || warn "Asterisk failed to start — check: journalctl -u asterisk"
fi

sleep 1
systemctl is-active --quiet asterisk 2>/dev/null \
  && info "Asterisk is running" \
  || warn "Asterisk does not appear to be running"

# =============================================================================
# WRITE config.py
# =============================================================================
section "Writing config.py"

cat > "$REPO_DIR/config.py" <<PYEOF
# =============================================================================
# PoC AI Proxy — Configuration  (auto-generated by install.sh — $(date))
# All paths are relative to this file's directory.
# =============================================================================
import os
_HERE = os.path.dirname(os.path.abspath(__file__))

# Language: "dutch", "english", "french", "german", "spanish"
LANGUAGE = "$LANGUAGE"

# Network
MY_IP    = "$PUBLIC_IP"
PHONE_IP = ""

LISTEN_PORT   = 5060
ASTERISK_IP   = "127.0.0.1"
ASTERISK_PORT = 5061

RTP_PORT    = 19998
TBCP_PORT   = 19999
SERVER_SSRC = 0x12345678

# API keys
# DeepSeek: https://platform.deepseek.com  (top up \$1-2 for months of use)
DEEPSEEK_API_KEY = "$DEEPSEEK_API_KEY"
# Groq:     https://console.groq.com       (free tier available)
GROQ_API_KEY     = "$GROQ_API_KEY"

# Paths — all relative to this file, so the repo is fully portable
WHISPER          = os.path.join(_HERE, "whisper.cpp", "build", "bin", "whisper-cli")
MODEL            = os.path.join(_HERE, "whisper.cpp", "models", "ggml-base.bin")
HOLD_MUSIC_FILES = [os.path.join(_HERE, "beepboop.wav")]
LOG_FILE         = os.path.join(_HERE, "sip_proxy.log")

# =============================================================================
# Language profiles — add new ones here
# Format: "key": (whisper_lang_code, edge_tts_voice, system_prompt)
# List TTS voices:  edge-tts --list-voices
# =============================================================================
LANGUAGE_PROFILES = {
    "dutch": (
        "nl",
        "nl-BE-ArnaudNeural",
        "Je bent een assistent op een portofoon. "
        "Antwoord ALTIJD in het Nederlands. Maximaal 2 zinnen."
    ),
    "english": (
        "en",
        "en-US-GuyNeural",
        "You are an assistant on a walkie-talkie radio. "
        "ALWAYS reply in English. Maximum 2 sentences."
    ),
    "french": (
        "fr",
        "fr-FR-HenriNeural",
        "Tu es un assistant sur un talkie-walkie. "
        "Réponds TOUJOURS en français. Maximum 2 phrases."
    ),
    "german": (
        "de",
        "de-DE-KillianNeural",
        "Du bist ein Assistent auf einem Walkie-Talkie. "
        "Antworte IMMER auf Deutsch. Maximal 2 Sätze."
    ),
    "spanish": (
        "es",
        "es-ES-AlvaroNeural",
        "Eres un asistente en un walkie-talkie. "
        "Responde SIEMPRE en español. Máximo 2 frases."
    ),
}
PYEOF

if [[ -f "$REPO_DIR/config.py" ]]; then
  chown "$SERVICE_USER:$SERVICE_USER" "$REPO_DIR/config.py"
  chmod 600 "$REPO_DIR/config.py"
  info "config.py written (permissions: 600)"
else
  warn "config.py could not be written — check disk space / permissions"
fi

# =============================================================================
# SYSTEMD SERVICE
# Bake real absolute paths in — systemd does NOT expand env vars in
# WorkingDirectory= so we write them directly here.
# =============================================================================
section "Installing systemd service"

PYTHON_BIN="$(command -v python3 || echo /usr/bin/python3)"

cat > /etc/systemd/system/poc-proxy.service <<SVCEOF
[Unit]
Description=PoC AI Proxy (SIP/RTP/TBCP walkie-talkie AI)
After=network.target asterisk.service
Wants=asterisk.service

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=$PYTHON_BIN $REPO_DIR/poc_proxy.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
TimeoutStartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

if [[ -f /etc/systemd/system/poc-proxy.service ]]; then
  systemctl daemon-reload >> "$INSTALL_LOG" 2>&1 \
    && systemctl enable poc-proxy >> "$INSTALL_LOG" 2>&1 \
    && info "poc-proxy.service enabled (will start at boot)" \
    || warn "systemctl enable failed — try: sudo systemctl daemon-reload && sudo systemctl enable poc-proxy"

  echo "  → Starting poc-proxy now"
  systemctl start poc-proxy >> "$INSTALL_LOG" 2>&1 \
    && info "poc-proxy started" \
    || warn "poc-proxy failed to start — check: sudo journalctl -u poc-proxy -n 30"

  sleep 2
  if systemctl is-active --quiet poc-proxy; then
    info "poc-proxy is running ✓"
  else
    warn "poc-proxy does not appear to be running — check: sudo journalctl -u poc-proxy -n 30"
  fi
else
  warn "Failed to write poc-proxy.service — check /etc/systemd/system/ permissions"
fi

# =============================================================================
# DONE
# =============================================================================
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║        Installation complete! ✓          ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "    Install dir : ${BOLD}$REPO_DIR${NC}"
echo -e "    Language    : ${BOLD}$LANGUAGE${NC}"
echo -e "    Server IP   : ${BOLD}$PUBLIC_IP${NC}"
echo -e "    Config      : ${BOLD}$REPO_DIR/config.py${NC}"
echo -e "    Full log    : ${BOLD}$INSTALL_LOG${NC}"
echo ""

if [[ ${#WARNINGS[@]} -gt 0 ]]; then
  echo -e "  ${YELLOW}${BOLD}Warnings (review before starting):${NC}"
  for w in "${WARNINGS[@]}"; do
    echo -e "    ${YELLOW}⚠${NC}  $w"
  done
  echo ""
fi

echo "  ── Next steps ───────────────────────────────────────"
if [[ -z "$DEEPSEEK_API_KEY" ]] || [[ -z "$GROQ_API_KEY" ]]; then
  echo -e "  ${YELLOW}  Edit config then restart the proxy:${NC}"
  echo -e "    nano $REPO_DIR/config.py"
  echo -e "    sudo systemctl restart poc-proxy"
  echo ""
fi
echo -e "    ${BOLD}sudo journalctl -u poc-proxy -f${NC}         # follow logs"
echo -e "    ${BOLD}sudo systemctl restart poc-proxy${NC}        # restart after config changes"
echo -e "    ${BOLD}sudo asterisk -rx 'sip show peers'${NC}      # check phone registration"
echo ""
