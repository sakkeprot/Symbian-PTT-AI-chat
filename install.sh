#!/usr/bin/env bash
# =============================================================================
# PoC AI Proxy — Install Script
# Tested on Ubuntu 22.04 / 24.04 (AWS EC2 or any VPS)
# Run as: sudo bash install.sh
# =============================================================================
set -e

REPO_DIR="/home/ubuntu/poc-ai-proxy"
SERVICE_USER="ubuntu"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
section() { echo -e "\n${GREEN}=== $* ===${NC}"; }

if [[ $EUID -ne 0 ]]; then
  echo -e "${RED}Please run as root: sudo bash install.sh${NC}"; exit 1
fi

# ---------------------------------------------------------------------------
section "System packages"
# ---------------------------------------------------------------------------
apt-get update -qq
apt-get install -y \
  python3 python3-pip python3-venv \
  ffmpeg \
  espeak-ng \
  asterisk \
  git cmake build-essential \
  libssl-dev libsrtp2-dev \
  curl wget

# AMR codec support (needed by ffmpeg for AMR-NB encode/decode)
apt-get install -y libvo-amrwbenc-dev libopencore-amrnb-dev libopencore-amrwb-dev || true

# Rebuild ffmpeg with AMR support if the package version lacks it
if ! ffmpeg -codecs 2>/dev/null | grep -q libopencore_amrnb; then
  warn "System ffmpeg lacks AMR-NB support — building from source (takes ~5 min)"
  apt-get install -y nasm yasm libx264-dev libmp3lame-dev libopus-dev
  cd /tmp
  wget -q https://ffmpeg.org/releases/ffmpeg-6.1.tar.gz
  tar xf ffmpeg-6.1.tar.gz
  cd ffmpeg-6.1
  ./configure --enable-libopencore-amrnb --enable-libopencore-amrwb \
              --enable-version3 --enable-gpl --enable-nonfree \
              --enable-libmp3lame --enable-libopus \
              --prefix=/usr/local --disable-doc --disable-htmlpages \
              --disable-manpages --disable-podpages --disable-txtpages
  make -j"$(nproc)"
  make install
  ldconfig
  cd /home/ubuntu
  info "ffmpeg built with AMR-NB support"
fi

# ---------------------------------------------------------------------------
section "Python dependencies"
# ---------------------------------------------------------------------------
pip3 install --break-system-packages requests edge-tts 2>/dev/null \
  || pip3 install requests edge-tts

# ---------------------------------------------------------------------------
section "whisper.cpp  (local STT fallback)"
# ---------------------------------------------------------------------------
if [[ ! -f /home/ubuntu/whisper.cpp/build/bin/whisper-cli ]]; then
  info "Cloning and building whisper.cpp…"
  sudo -u "$SERVICE_USER" bash -c "
    cd /home/ubuntu
    git clone https://github.com/ggerganov/whisper.cpp.git
    cd whisper.cpp
    cmake -B build -DWHISPER_BUILD_EXAMPLES=ON
    cmake --build build --config Release -j\$(nproc)
    mkdir -p models
    bash models/download-ggml-model.sh base
  "
  info "whisper.cpp ready"
else
  info "whisper.cpp already installed — skipping"
fi

# ---------------------------------------------------------------------------
section "Asterisk configuration"
# ---------------------------------------------------------------------------
ASTERISK_CONF_DIR="/etc/asterisk"

# Detect public IP
PUBLIC_IP=$(curl -s https://api.ipify.org || curl -s https://ifconfig.me || echo "YOUR_PUBLIC_IP")
info "Detected public IP: $PUBLIC_IP"

# Detect local subnet
LOCAL_NET=$(ip route | awk '/^[0-9]/ && !/default/ {print $1}' | head -1)
[[ -z "$LOCAL_NET" ]] && LOCAL_NET="192.168.0.0/255.255.0.0"
info "Detected local net: $LOCAL_NET"

# Write sip.conf
cp "$(dirname "$0")/sip.conf" "$ASTERISK_CONF_DIR/sip.conf"

# Substitute placeholders
sed -i "s|YOUR_PUBLIC_IP|$PUBLIC_IP|g"               "$ASTERISK_CONF_DIR/sip.conf"
sed -i "s|172.31.0.0/255.255.0.0|$LOCAL_NET|g"       "$ASTERISK_CONF_DIR/sip.conf"

info "sip.conf written to $ASTERISK_CONF_DIR/sip.conf"

# Minimal extensions.conf if it is empty / default
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
  info "Asterisk running"
else
  warn "Asterisk failed to start — check: journalctl -u asterisk"
fi

# ---------------------------------------------------------------------------
section "Installing PoC AI Proxy"
# ---------------------------------------------------------------------------
install -d -o ubuntu -g ubuntu "$REPO_DIR"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for f in poc_proxy.py config.py requirements.txt; do
  if [[ -f "$SCRIPT_DIR/$f" ]]; then
    cp "$SCRIPT_DIR/$f" "$REPO_DIR/$f"
    chown ubuntu:ubuntu "$REPO_DIR/$f"
  fi
done

# ---------------------------------------------------------------------------
section "Systemd service"
# ---------------------------------------------------------------------------
cp "$SCRIPT_DIR/poc-proxy.service" /etc/systemd/system/poc-proxy.service
systemctl daemon-reload
systemctl enable poc-proxy

echo ""
info "Installation complete."
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Edit  $REPO_DIR/config.py"
echo "       — Set MY_IP to your server's public IP"
echo "       — Add your DEEPSEEK_API_KEY and GROQ_API_KEY"
echo "       — Set LANGUAGE (dutch/english/french/german/spanish)"
echo ""
echo "  2. (Optional) Copy a hold-music WAV to /home/ubuntu/beepboop.wav"
echo ""
echo "  3. Start the proxy:"
echo "       sudo systemctl start poc-proxy"
echo "       sudo journalctl -u poc-proxy -f"
echo ""
echo "  4. Check Asterisk:"
echo "       sudo asterisk -rx 'sip show peers'"
echo "       sudo asterisk -rx 'sip reload'"
