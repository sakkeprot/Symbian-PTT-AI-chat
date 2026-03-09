# PoC AI Proxy

A SIP/RTP proxy that turns a **PoC (Push-to-Talk over Cellular) phone** into an AI walkie-talkie. Press PTT → speak → get an AI response spoken back over the radio channel.

```
Nokia/Symbian PoC phone
        │  SIP (UDP 5060)
        ▼
  poc_proxy.py  ◄──► Asterisk (SIP UDP 5061)
        │
        ├── RTP (UDP 19998)   AMR-NB audio
        └── TBCP (UDP 19999)  Floor control
              │
              ▼
    ┌─────────────────────┐
    │  Groq Whisper STT   │  speech → text
    │  DeepSeek LLM       │  text → reply
    │  edge-tts / espeak  │  reply → speech
    └─────────────────────┘
```

---

## Requirements

| Component | Purpose |
|-----------|---------|
| Ubuntu 22.04 / 24.04 | Tested OS |
| Asterisk 18+ | SIP registrar |
| ffmpeg (with AMR-NB) | Audio codec conversion |
| edge-tts | Neural TTS (preferred) |
| espeak-ng | TTS fallback |
| whisper.cpp | Local STT fallback |
| Groq API key | Cloud STT (Whisper large-v3) |
| DeepSeek API key | LLM replies |

---

## Quick install

```bash
git clone https://github.com/YOUR_USERNAME/poc-ai-proxy.git
cd poc-ai-proxy
sudo bash install.sh
```

The script will:
- Install system packages (`ffmpeg`, `espeak-ng`, `asterisk`, build tools)
- Build **ffmpeg** with AMR-NB support if the package version lacks it
- Clone and build **whisper.cpp** with the `base` model
- Write `/etc/asterisk/sip.conf` (auto-detects your public IP and subnet)
- Install the systemd service `poc-proxy.service`

---

## Manual setup (step by step)

### 1 — System packages

```bash
sudo apt-get update
sudo apt-get install -y \
  python3 python3-pip ffmpeg espeak-ng asterisk \
  git cmake build-essential libssl-dev
```

Check that ffmpeg has AMR-NB support:

```bash
ffmpeg -codecs 2>/dev/null | grep amr
# should show: libopencore_amrnb
```

If it doesn't, install the codec libraries and rebuild (the install script handles this automatically):

```bash
sudo apt-get install -y \
  libopencore-amrnb-dev libopencore-amrwb-dev libvo-amrwbenc-dev
```

### 2 — Python dependencies

```bash
pip3 install -r requirements.txt
```

### 3 — whisper.cpp  (local STT fallback)

```bash
cd ~
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp
cmake -B build -DWHISPER_BUILD_EXAMPLES=ON
cmake --build build --config Release -j$(nproc)

# Download the base model (~145 MB)
bash models/download-ggml-model.sh base
```

> You can use a larger model (e.g. `small`, `medium`) for better accuracy at the cost of speed.

### 4 — Asterisk

Install:

```bash
sudo apt-get install -y asterisk
```

Copy the included `sip.conf`:

```bash
sudo cp sip.conf /etc/asterisk/sip.conf
```

Edit the two lines that need your values:

```bash
sudo nano /etc/asterisk/sip.conf
```

```ini
externaddr=YOUR_PUBLIC_IP        ; e.g. 51.20.75.225
localnet=172.31.0.0/255.255.0.0  ; your VPC/LAN subnet
```

Reload Asterisk:

```bash
sudo systemctl restart asterisk

# Verify SIP is listening on port 5061
sudo asterisk -rx 'sip show settings' | grep 'UDP Bindaddress'
```

### 5 — Configure the proxy

```bash
cp config.py.example config.py   # or just open config.py directly
nano config.py
```

**Required fields:**

| Field | Description |
|-------|-------------|
| `LANGUAGE` | `"dutch"`, `"english"`, `"french"`, `"german"`, or `"spanish"` |
| `MY_IP` | Public IP of this server (used in SDP) |
| `DEEPSEEK_API_KEY` | Get one at https://platform.deepseek.com |
| `GROQ_API_KEY` | Get one at https://console.groq.com (optional but recommended) |

**Optional:**

| Field | Description |
|-------|-------------|
| `HOLD_MUSIC_FILES` | List of WAV paths to play while processing |
| `WHISPER` / `MODEL` | Paths to your whisper-cli binary and model |

### 6 — Firewall / Security Groups

Open the following UDP ports inbound:

| Port | Protocol | Purpose |
|------|----------|---------|
| 5060 | UDP | SIP (proxy entry point) |
| 19998 | UDP | RTP audio |
| 19999 | UDP | TBCP floor control |

Port 5061 (Asterisk) should be **localhost only** — the proxy relays to it internally.

### 7 — Run

**Manually (for testing):**

```bash
python3 poc_proxy.py
```

**As a systemd service:**

```bash
sudo cp poc-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now poc-proxy

# Follow logs
sudo journalctl -u poc-proxy -f
```

---

## Phone setup (Nokia / Symbian PoC client)

1. Register the phone against your server IP on SIP port **5060**.
2. Use the account name **`symbian`** — the proxy identifies phones by the `symbian` string in the User-Agent header.
3. No password is required (Asterisk is configured with `insecure=register`).
4. Set audio codec preference to **AMR-NB** (payload type 106) if your client allows it; otherwise ulaw/alaw will still work via Asterisk.

---

## Adding a new language

Open `config.py` and add a row to `LANGUAGE_PROFILES`:

```python
"portuguese": (
    "pt",                          # Whisper language code
    "pt-BR-AntonioNeural",         # edge-tts voice  (edge-tts --list-voices)
    "Você é um assistente de rádio. Responda SEMPRE em português. Máximo 2 frases."
),
```

Then set `LANGUAGE = "portuguese"` and restart.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ffmpeg: unknown encoder libopencore_amrnb` | Rebuild ffmpeg with AMR support (see step 1) |
| No audio heard | Check RTP port 19998 is open; verify `MY_IP` in config.py |
| STT returns empty | Check Groq key; try local whisper fallback |
| Phone won't register | Check Asterisk is running on port 5061: `ss -ulnp \| grep 5061` |
| TTS sounds wrong language | Verify `LANGUAGE` in config.py and restart the service |

**Useful diagnostic commands:**

```bash
# Proxy logs
sudo journalctl -u poc-proxy -f

# Asterisk live console
sudo asterisk -rvvv

# Check registered SIP peers
sudo asterisk -rx 'sip show peers'

# Reload SIP config without restarting
sudo asterisk -rx 'sip reload'

# Check ports are bound
ss -ulnp | grep -E '5060|5061|19998|19999'
```

---

## File overview

```
poc-ai-proxy/
├── poc_proxy.py        # Main proxy (SIP / RTP / TBCP / pipeline)
├── config.py           # All configuration — edit this
├── requirements.txt    # Python dependencies
├── sip.conf            # Asterisk SIP config
├── poc-proxy.service   # systemd unit file
├── install.sh          # One-shot install script
└── README.md
```

---

## License

MIT
