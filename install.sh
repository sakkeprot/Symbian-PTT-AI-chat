#!/usr/bin/env bash
# =============================================================================
# PoC AI Proxy — Install Script
# Tested on Ubuntu 22.04 / 24.04 (AWS EC2 or any VPS)
# Run as: sudo bash install.sh   (from inside the cloned repo)
# =============================================================================
set -e

# REPO_DIR is wherever this script lives — no hardcoded /home/ubuntu paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$SCRIPT_DIR"

# The user who should own the files (whoever cloned the repo, or ubuntu)
if [[ -n "$SUDO_USER" ]]; then
  SERVICE_USER="$SUDO_USER"
else
  SERVICE_USER="ubuntu"
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
section() { echo -e "\n${GREEN}========================================${NC}"
            echo -e "${GREEN}  $*${NC}"
            echo -e "${GREEN}========================================${NC}"; }
ask()     { echo -e "${CYAN}${BOLD}$*${NC}"; }

if [[ $EUID -ne 0 ]]; then
  echo -e "${RED}Please run as root:  sudo bash install.sh${NC}"; exit 1
fi

# =============================================================================
# STEP 0 — Welcome
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
echo "  Turns a Nokia/Symbian PoC phone into an AI walkie-talkie"
echo ""
echo -e "  Installing into: ${BOLD}$REPO_DIR${NC}"
echo ""
read -rp "  Press ENTER to begin..." _

# =============================================================================
# STEP 1 — Language
# =============================================================================
section "Step 1 of 4 — Language"
echo ""
echo "  Choose the language for speech recognition, text-to-speech"
echo "  and AI replies:"
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
info "Language set to: $LANGUAGE"

# =============================================================================
# STEP 2 — DeepSeek API key
# =============================================================================
section "Step 2 of 4 — DeepSeek API key  (AI replies)"
echo ""
echo "  DeepSeek is the AI that generates spoken replies."
echo ""
echo -e "  ${BOLD}How to get your key:${NC}"
echo "    1. Go to  https://platform.deepseek.com"
echo "    2. Sign up and log in"
echo "    3. Click 'API Keys' in the left sidebar → 'Create new key'"
echo "    4. Copy the key — it looks like:  sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
echo ""
echo -e "  ${YELLOW}${BOLD}💳  Important — add credit to your account:${NC}"
echo -e "  ${YELLOW}  DeepSeek requires a small balance before it will respond."
echo -e "  A top-up of just \$1–\$2 is enough for months of normal use."
echo -e "  Top up at:  platform.deepseek.com  →  'Billing' → 'Top up'${NC}"
echo ""
while true; do
  ask "  Paste your DeepSeek API key  (or press ENTER to skip and set later):"
  read -rp "  > " DEEPSEEK_API_KEY
  if [[ -z "$DEEPSEEK_API_KEY" ]]; then
    warn "Skipped — add DEEPSEEK_API_KEY to $REPO_DIR/config.py before starting"
    break
  elif [[ "$DEEPSEEK_API_KEY" == sk-* ]]; then
    info "DeepSeek key accepted."
    break
  else
    echo -e "  ${RED}That doesn't look right — DeepSeek keys start with 'sk-'."
    echo -e "  Try again, or press ENTER to skip for now.${NC}"
    echo ""
  fi
done

# =============================================================================
# STEP 3 — Groq API key
# =============================================================================
section "Step 3 of 4 — Groq API key  (Speech recognition)"
echo ""
echo "  Groq runs Whisper large-v3 — the fastest, most accurate"
echo "  speech-to-text available. It is free to sign up."
echo ""
echo -e "  ${BOLD}How to get your key:${NC}"
echo "    1. Go to  https://console.groq.com"
echo "    2. Sign up for free and log in"
echo "    3. Click 'API Keys' in the sidebar → 'Create API Key'"
echo "    4. Copy the key — it looks like:  gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
echo ""
echo -e "  ${YELLOW}Note: if you skip this, speech recognition falls back to"
echo -e "  local whisper.cpp (slower, lower accuracy).${NC}"
echo ""
while true; do
  ask "  Paste your Groq API key  (or press ENTER to skip):"
  read -rp "  > " GROQ_API_KEY
  if [[ -z "$GROQ_API_KEY" ]]; then
    warn "Skipped — local whisper.cpp will be used as STT fallback"
    break
  elif [[ "$GROQ_API_KEY" == gsk_* ]]; then
    info "Groq key accepted."
    break
  else
    echo -e "  ${RED}That doesn't look right — Groq keys start with 'gsk_'."
    echo -e "  Try again, or press ENTER to skip for now.${NC}"
    echo ""
  fi
done

# =============================================================================
# STEP 4 — Confirm
# =============================================================================
section "Step 4 of 4 — Confirm & install"
echo ""
echo "  Ready to install with these settings:"
echo ""
echo -e "    Install dir : ${BOLD}$REPO_DIR${NC}"
echo -e "    Language    : ${BOLD}$LANGUAGE${NC}"
if [[ -n "$DEEPSEEK_API_KEY" ]]; then
  echo -e "    DeepSeek    : ${GREEN}✓ set  (${DEEPSEEK_API_KEY:0:8}...)${NC}"
else
  echo -e "    DeepSeek    : ${YELLOW}⚠ not set — add to config.py before starting${NC}"
fi
if [[ -n "$GROQ_API_KEY" ]]; then
  echo -e "    Groq STT    : ${GREEN}✓ set  (${GROQ_API_KEY:0:8}...)${NC}"
else
  echo -e "    Groq STT    : ${YELLOW}⚠ not set — will use local whisper fallback${NC}"
fi
echo ""
ask "  Proceed with installation? [Y/n]"
read -rp "  > " CONFIRM
if [[ "$CONFIRM" =~ ^[Nn] ]]; then
  echo "Aborted."; exit 0
fi

# =============================================================================
# SYSTEM PACKAGES
# =============================================================================
section "Installing system packages"
apt-get update -qq
apt-get install -y \
  python3 python3-pip python3-venv \
  ffmpeg \
  espeak-ng \
  asterisk \
  git cmake build-essential \
  libssl-dev libsrtp2-dev \
  curl wget

# AMR codec libraries
apt-get install -y libvo-amrwbenc-dev libopencore-amrnb-dev libopencore-amrwb-dev || true

# Rebuild ffmpeg with AMR-NB if the packaged version lacks it
if ! ffmpeg -codecs 2>/dev/null | grep -q libopencore_amrnb; then
  warn "System ffmpeg lacks AMR-NB support — building from source (~5 min)"
  apt-get install -y nasm yasm libx264-dev libmp3lame-dev libopus-dev
  cd /tmp
  wget -q https://ffmpeg.org/releases/ffmpeg-6.1.tar.gz
  tar xf ffmpeg-6.1.tar.gz
  cd ffmpeg-6.1
  ./configure \
    --enable-libopencore-amrnb --enable-libopencore-amrwb \
    --enable-version3 --enable-gpl --enable-nonfree \
    --enable-libmp3lame --enable-libopus \
    --prefix=/usr/local \
    --disable-doc --disable-htmlpages --disable-manpages \
    --disable-podpages --disable-txtpages
  make -j"$(nproc)"
  make install
  ldconfig
  cd "$REPO_DIR"
  info "ffmpeg built with AMR-NB support"
fi

# =============================================================================
# PYTHON DEPENDENCIES
# =============================================================================
section "Installing Python dependencies"
pip3 install --break-system-packages requests edge-tts 2>/dev/null \
  || pip3 install requests edge-tts

# =============================================================================
# WHISPER.CPP  — cloned inside the repo directory
# =============================================================================
section "Building whisper.cpp  (local STT fallback)"
WHISPER_DIR="$REPO_DIR/whisper.cpp"
if [[ ! -f "$WHISPER_DIR/build/bin/whisper-cli" ]]; then
  info "Cloning whisper.cpp into $WHISPER_DIR …"
  sudo -u "$SERVICE_USER" bash -c "
    cd '$REPO_DIR'
    git clone https://github.com/ggerganov/whisper.cpp.git whisper.cpp
    cd whisper.cpp
    cmake -B build -DWHISPER_BUILD_EXAMPLES=ON
    cmake --build build --config Release -j\$(nproc)
    mkdir -p models
    bash models/download-ggml-model.sh base
  "
  info "whisper.cpp ready at $WHISPER_DIR"
else
  info "whisper.cpp already present — skipping"
fi

# =============================================================================
# ASTERISK
# =============================================================================
section "Configuring Asterisk"
ASTERISK_CONF_DIR="/etc/asterisk"

PUBLIC_IP=$(curl -s https://api.ipify.org 2>/dev/null \
         || curl -s https://ifconfig.me 2>/dev/null \
         || echo "YOUR_PUBLIC_IP")
info "Detected public IP: $PUBLIC_IP"

LOCAL_NET=$(ip route | awk '/^[0-9]/ && !/default/ {print $1}' | head -1)
[[ -z "$LOCAL_NET" ]] && LOCAL_NET="192.168.0.0/255.255.0.0"
info "Detected local subnet: $LOCAL_NET"

cp "$REPO_DIR/sip.conf" "$ASTERISK_CONF_DIR/sip.conf"
sed -i "s|YOUR_PUBLIC_IP|$PUBLIC_IP|g"         "$ASTERISK_CONF_DIR/sip.conf"
sed -i "s|172.31.0.0/255.255.0.0|$LOCAL_NET|g" "$ASTERISK_CONF_DIR/sip.conf"
info "sip.conf written"

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
fi

systemctl enable asterisk
systemctl restart asterisk
sleep 2
if systemctl is-active --quiet asterisk; then
  info "Asterisk is running"
else
  warn "Asterisk failed to start — check: journalctl -u asterisk"
fi

# =============================================================================
# GENERATE config.py  (uses _HERE-relative paths — works in any location)
# =============================================================================
section "Writing config.py"
cat > "$REPO_DIR/config.py" <<PYEOF
# =============================================================================
# PoC AI Proxy — Configuration  (auto-generated by install.sh)
# All paths are relative to this file's location — move the whole folder
# and everything still works.
# =============================================================================
import os
_HERE = os.path.dirname(os.path.abspath(__file__))

# Language for STT, TTS, and AI responses
# Options: "dutch", "english", "french", "german", "spanish"
LANGUAGE = "$LANGUAGE"

# Network
MY_IP    = "$PUBLIC_IP"   # Public IP of this server — used in SDP offers
PHONE_IP = ""             # IP of the PoC phone (informational only)

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

# Paths — relative to this config file, so the repo is fully portable
WHISPER          = os.path.join(_HERE, "whisper.cpp", "build", "bin", "whisper-cli")
MODEL            = os.path.join(_HERE, "whisper.cpp", "models", "ggml-base.bin")
HOLD_MUSIC_FILES = [os.path.join(_HERE, "beepboop.wav")]
LOG_FILE         = os.path.join(_HERE, "sip_proxy.log")

# =============================================================================
# Language profiles
# Format: "key": (whisper_lang_code, edge_tts_voice, system_prompt)
# Add new languages here.  List TTS voices:  edge-tts --list-voices
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

chown "$SERVICE_USER:$SERVICE_USER" "$REPO_DIR/config.py"
chmod 600 "$REPO_DIR/config.py"
info "config.py written"

# =============================================================================
# SYSTEMD SERVICE
# Write the install dir to an env file so the service unit is location-agnostic
# =============================================================================
section "Installing systemd service"

# Write the env file that the service unit reads
echo "INSTALL_DIR=$REPO_DIR" > /etc/poc-proxy.env
chmod 600 /etc/poc-proxy.env
info "Wrote /etc/poc-proxy.env  (INSTALL_DIR=$REPO_DIR)"

cp "$REPO_DIR/poc-proxy.service" /etc/systemd/system/poc-proxy.service
systemctl daemon-reload
systemctl enable poc-proxy

# =============================================================================
# DONE
# =============================================================================
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║        Installation complete! ✓          ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"
echo "  Summary:"
echo -e "    Install dir : ${BOLD}$REPO_DIR${NC}"
echo -e "    Language    : ${BOLD}$LANGUAGE${NC}"
echo -e "    Server IP   : ${BOLD}$PUBLIC_IP${NC}"
echo -e "    Config      : ${BOLD}$REPO_DIR/config.py${NC}"
echo ""

if [[ -z "$DEEPSEEK_API_KEY" ]] || [[ -z "$GROQ_API_KEY" ]]; then
  echo -e "  ${YELLOW}⚠  One or more API keys were not set."
  echo "     Edit the config file before starting the proxy:"
  echo -e "     nano $REPO_DIR/config.py${NC}"
  echo ""
fi

echo "  ── Start the proxy ──────────────────────────────────"
echo -e "    ${BOLD}sudo systemctl start poc-proxy${NC}"
echo ""
echo "  ── Follow live logs ─────────────────────────────────"
echo -e "    ${BOLD}sudo journalctl -u poc-proxy -f${NC}"
echo ""
echo "  ── Check Asterisk SIP peers ─────────────────────────"
echo -e "    ${BOLD}sudo asterisk -rx 'sip show peers'${NC}"
echo ""
