# =============================================================================
# PoC AI Proxy — Configuration
# Edit this file before running poc_proxy.py
# =============================================================================

# ---- Language ----------------------------------------------------------------
# Controls STT language, TTS voice, and the AI system prompt.
# Supported values (case-insensitive):
#   "dutch"   → nl-BE-ArnaudNeural,    Whisper lang=nl
#   "english" → en-US-GuyNeural,       Whisper lang=en
#   "french"  → fr-FR-HenriNeural,     Whisper lang=fr
#   "german"  → de-DE-KillianNeural,   Whisper lang=de
#   "spanish" → es-ES-AlvaroNeural,    Whisper lang=es
LANGUAGE = "dutch"

# ---- Network ----------------------------------------------------------------
MY_IP    = ""   # Public or LAN IP of this server — used in SDP offers
PHONE_IP = ""   # IP of the PoC phone (informational only)

# SIP proxy ports
LISTEN_PORT   = 5060          # Port this proxy listens on
ASTERISK_IP   = "127.0.0.1"
ASTERISK_PORT = 5061          # Must match udpbindaddr in sip.conf

# RTP / TBCP ports
RTP_PORT    = 19998
TBCP_PORT   = 19999
SERVER_SSRC = 0x12345678

# ---- API keys ---------------------------------------------------------------
# Get your DeepSeek key at: https://platform.deepseek.com
DEEPSEEK_API_KEY = ""

# Get your Groq key at: https://console.groq.com
# Used for Whisper large-v3 STT — leave blank to use only local whisper.cpp
GROQ_API_KEY = ""

# ---- Local paths ------------------------------------------------------------
# Path to whisper-cli binary (local STT fallback if Groq is unavailable)
WHISPER = "/home/ubuntu/whisper.cpp/build/bin/whisper-cli"
MODEL   = "/home/ubuntu/whisper.cpp/models/ggml-base.bin"

# WAV files to play as hold music while the AI is processing
# Add as many paths as you like; one is chosen at random each time
HOLD_MUSIC_FILES = ["/home/ubuntu/beepboop.wav"]

# ---- Logging ----------------------------------------------------------------
LOG_FILE = "/home/ubuntu/sip_proxy.log"

# =============================================================================
# Language profiles — add new languages here
# Format: "key": (whisper_lang, edge_tts_voice, system_prompt)
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
