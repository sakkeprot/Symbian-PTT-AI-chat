#!/usr/bin/env python3
"""
PoC (Push-to-Talk over Cellular) AI Proxy
==========================================
A SIP/RTP proxy that intercepts PTT calls from a PoC-enabled phone,
performs speech-to-text, sends the transcript to an LLM, and speaks
the reply back over the radio channel using TTS.

Protocol stack: SIP (registration/signalling) + AMR-NB RTP (audio) + TBCP (floor control)

Requirements:
    pip install requests
    apt install ffmpeg espeak-ng
    pip install edge-tts          # optional but recommended
    # whisper.cpp built locally   # optional fallback STT

Configuration: edit the CONFIGURATION block below before running.
"""

import socket, re, threading, time, struct, subprocess, tempfile
import os, requests, json, sys, random
from datetime import datetime

# =============================================================================
# CONFIGURATION
# =============================================================================

# ---- Language ----------------------------------------------------------------
# Choose the language for STT, TTS, and the AI assistant.
# Supported values (case-insensitive):
#   "dutch"      → nl-BE-ArnaudNeural TTS, Whisper lang=nl, Dutch system prompt
#   "english"    → en-US-GuyNeural TTS,   Whisper lang=en, English system prompt
#   "french"     → fr-FR-HenriNeural TTS, Whisper lang=fr, French system prompt
#   "german"     → de-DE-KillianNeural TTS, Whisper lang=de, German system prompt
#   "spanish"    → es-ES-AlvaroNeural TTS, Whisper lang=es, Spanish system prompt
LANGUAGE = "dutch"

# ---- Network ----------------------------------------------------------------
MY_IP        = ""          # Public/LAN IP of this server (used in SDP)
PHONE_IP     = ""          # IP of the PoC phone (informational)

# ---- API keys ---------------------------------------------------------------
DEEPSEEK_API_KEY = ""      # https://platform.deepseek.com
GROQ_API_KEY     = ""      # https://console.groq.com  (for Whisper large-v3 STT)

# ---- Local paths ------------------------------------------------------------
WHISPER          = "/home/ubuntu/whisper.cpp/build/bin/whisper-cli"   # local STT fallback
MODEL            = "/home/ubuntu/whisper.cpp/models/ggml-base.bin"
HOLD_MUSIC_FILES = ["/home/ubuntu/beepboop.wav"]  # WAV files to play while processing

# ---- Ports ------------------------------------------------------------------
LISTEN_PORT   = 5060
ASTERISK_IP   = "127.0.0.1"
ASTERISK_PORT = 5061
RTP_PORT      = 19998
TBCP_PORT     = 19999
SERVER_SSRC   = 0x12345678

# ---- API endpoints ----------------------------------------------------------
DEEPSEEK_URL  = "https://api.deepseek.com/chat/completions"
GROQ_STT_URL  = "https://api.groq.com/openai/v1/audio/transcriptions"

# =============================================================================
# LANGUAGE PROFILES
# Each entry: (whisper_lang_code, edge_tts_voice, system_prompt)
# =============================================================================
LANGUAGE_PROFILES = {
    "dutch": (
        "nl",
        "nl-BE-ArnaudNeural",
        "Je bent een assistent op een portofoon. Antwoord ALTIJD in het Nederlands. Maximaal 2 zinnen."
    ),
    "english": (
        "en",
        "en-US-GuyNeural",
        "You are an assistant on a walkie-talkie radio. ALWAYS reply in English. Maximum 2 sentences."
    ),
    "french": (
        "fr",
        "fr-FR-HenriNeural",
        "Tu es un assistant sur un talkie-walkie. Réponds TOUJOURS en français. Maximum 2 phrases."
    ),
    "german": (
        "de",
        "de-DE-KillianNeural",
        "Du bist ein Assistent auf einem Walkie-Talkie. Antworte IMMER auf Deutsch. Maximal 2 Sätze."
    ),
    "spanish": (
        "es",
        "es-ES-AlvaroNeural",
        "Eres un asistente en un walkie-talkie. Responde SIEMPRE en español. Máximo 2 frases."
    ),
}

def _get_language_profile():
    key = LANGUAGE.lower().strip()
    if key not in LANGUAGE_PROFILES:
        raise ValueError(
            f"Unsupported LANGUAGE '{LANGUAGE}'. "
            f"Choose from: {', '.join(LANGUAGE_PROFILES)}"
        )
    return LANGUAGE_PROFILES[key]

WHISPER_LANG, TTS_VOICE, SYSTEM_PROMPT = _get_language_profile()

# =============================================================================
# LOGGING
# =============================================================================
LOG_FILE = "/home/ubuntu/sip_proxy.log"

def log(tag, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] [{tag}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def log_sip(direction, addr, msg):
    first_line = msg.split('\r\n')[0] if '\r\n' in msg else msg.split('\n')[0]
    log("SIP", f"{direction} {addr[0]}:{addr[1]} | {first_line}")
    log("SIP-FULL", f"{direction} {addr[0]}:{addr[1]}\n{msg}\n{'='*60}")

# =============================================================================
# AMR FRAME SIZES  (AMR-NB, RFC 3267)
# =============================================================================
FT_SPEECH_SIZES = {0: 12, 1: 13, 2: 15, 3: 17, 4: 19,
                   5: 20, 6: 26, 7: 31, 8: 5}

# =============================================================================
# GLOBAL STATE
# =============================================================================
burst_audio          = b""
granted              = False
server_speaking      = False
lock                 = threading.Lock()
last_client          = {}
conversation_history = []   # LLM message history, cleared on BYE

# Sockets
rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
rtp_sock.bind(("0.0.0.0", RTP_PORT))
rtp_sock.settimeout(1)

tbcp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tbcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
tbcp_sock.bind(("0.0.0.0", TBCP_PORT))
tbcp_sock.settimeout(1)

all_hold_music = []   # list of frame lists, one per loaded track

# =============================================================================
# HOLD MUSIC
# =============================================================================

def load_hold_music():
    global all_hold_music
    for path in HOLD_MUSIC_FILES:
        if not os.path.exists(path):
            log("HOLD", f"Not found, skipping: {path}")
            continue
        amr_path = f'/tmp/hold_{os.path.basename(path)}.amr'
        subprocess.run(
            ['ffmpeg', '-y', '-i', path, '-ar', '8000', '-ac', '1',
             '-c:a', 'libopencore_amrnb', '-b:a', '12.2k', amr_path],
            capture_output=True)
        if not os.path.exists(amr_path):
            log("HOLD", f"AMR encode failed: {path}")
            continue
        with open(amr_path, 'rb') as f:
            amr = f.read()
        os.unlink(amr_path)
        frames = []
        pos = 6
        while pos < len(amr):
            fh = amr[pos]
            ft = (fh >> 3) & 0xF
            sz = FT_SPEECH_SIZES.get(ft, 0)
            if sz == 0:
                pos += 1
                continue
            frames.append(amr[pos:pos + 1 + sz])
            pos += 1 + sz
        if frames:
            all_hold_music.append(frames)
            log("HOLD", f"Loaded {len(frames)} frames from {os.path.basename(path)}")
    log("HOLD", f"Total {len(all_hold_music)} hold music track(s) loaded")

# =============================================================================
# LLM  (DeepSeek)
# =============================================================================

def ask_deepseek(text):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    conversation_history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history
    payload = {"model": "deepseek-chat", "messages": messages}
    try:
        r = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=15)
        reply = r.json()["choices"][0]["message"]["content"].strip()
        conversation_history.append({"role": "assistant", "content": reply})
        log("LLM", f"History length: {len(conversation_history)} messages")
        return reply
    except Exception as e:
        log("LLM", f"ERR: {e}")
        conversation_history.pop()   # remove the user msg that failed
        return "Sorry, an error occurred."

# =============================================================================
# TTS
# =============================================================================

def tts_to_wav(text, wav_path):
    """
    Convert text to 8 kHz mono WAV.
    Tries edge-tts first (uses voice from language profile),
    falls back to espeak-ng.
    Prepends 1 s silence so the first word isn't clipped.
    """
    raw_wav = wav_path + '.raw.wav'
    try:
        mp3_path = wav_path + '.mp3'
        result = subprocess.run(
            ['edge-tts', '--voice', TTS_VOICE, '--text', text,
             '--write-media', mp3_path],
            capture_output=True, timeout=15)
        if os.path.exists(mp3_path):
            subprocess.run(
                ['ffmpeg', '-y', '-i', mp3_path, '-ar', '8000', '-ac', '1', raw_wav],
                capture_output=True, timeout=10)
            os.unlink(mp3_path)
            if os.path.exists(raw_wav):
                log("TTS", f"Used edge-tts voice: {TTS_VOICE}")
        if not os.path.exists(raw_wav):
            log("TTS", f"edge-tts failed: {result.stderr.decode(errors='ignore')[:200]}")
            raise Exception("edge-tts failed")
    except Exception as e:
        log("TTS", f"edge-tts failed ({e}), falling back to espeak-ng")
        espeak_lang = WHISPER_LANG   # good enough approximation
        subprocess.run(
            ['espeak-ng', '-v', espeak_lang, '-s', '150', '-w', raw_wav, text],
            capture_output=True)

    if not os.path.exists(raw_wav):
        return False

    # Prepend 1 s silence
    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'anullsrc=r=8000:cl=mono', '-i', raw_wav,
        '-filter_complex', '[0]atrim=0:1[s];[s][1]concat=n=2:v=0:a=1',
        '-ar', '8000', '-ac', '1', wav_path
    ], capture_output=True, timeout=10)
    os.unlink(raw_wav)
    return os.path.exists(wav_path)

# =============================================================================
# RTP / AMR helpers
# =============================================================================

def wav_to_amr_frames(wav_path):
    amr_path = wav_path + '.amr'
    subprocess.run(
        ['ffmpeg', '-y', '-i', wav_path, '-ar', '8000', '-ac', '1',
         '-c:a', 'libopencore_amrnb', '-b:a', '12.2k', amr_path],
        capture_output=True)
    if not os.path.exists(amr_path):
        return []
    with open(amr_path, 'rb') as f:
        amr = f.read()
    os.unlink(amr_path)
    pos = 6
    frames = []
    while pos < len(amr):
        fh = amr[pos]
        ft = (fh >> 3) & 0xF
        sz = FT_SPEECH_SIZES.get(ft, 0)
        if sz == 0:
            pos += 1
            continue
        frames.append(amr[pos:pos + 1 + sz])
        pos += 1 + sz
    return frames

def send_amr_frames(frames, dest_ip, dest_port, stop_event=None,
                    seq_start=1000, ts_start=0):
    seq = seq_start
    ts  = ts_start
    for i in range(0, len(frames), 8):
        if stop_event and stop_event.is_set():
            return (seq, ts)
        batch = frames[i:i + 8]
        toc = b""
        for j, fr in enumerate(batch):
            toc += bytes([fr[0] | 0x80]) if j < len(batch) - 1 else bytes([fr[0] & 0x7F])
        speech  = b"".join(fr[1:] for fr in batch)
        payload = bytes([0x20]) + toc + speech
        header  = struct.pack('>BBHII', 0x80, 0x6A, seq, ts, SERVER_SSRC)
        rtp_sock.sendto(header + payload, (dest_ip, dest_port))
        seq  = (seq + 1) & 0xFFFF
        ts  += 160 * len(batch)
        time.sleep(0.02 * len(batch))
    return (seq, ts)

def send_hold_music(dest_ip, dest_port, stop_event):
    if not all_hold_music:
        log("HOLD", "No hold music loaded")
        return
    frames = random.choice(all_hold_music)
    log("HOLD", f"Playing random hold music ({len(frames)} frames) -> {dest_ip}:{dest_port}")
    seq = 2000; ts = 0
    while not stop_event.is_set():
        seq, ts = send_amr_frames(frames, dest_ip, dest_port, stop_event, seq, ts)
    log("HOLD", "Hold music stopped")

def parse_amr_from_rtp(payload):
    amr_frames = b""
    i = 1
    toc = []
    while i < len(payload):
        b = payload[i]; i += 1
        F  = (b >> 7) & 1
        ft = (b >> 3) & 0xF
        toc.append((ft, b & 0x7F))
        if F == 0:
            break
    for ft, toc_byte in toc:
        sz = FT_SPEECH_SIZES.get(ft, 0)
        amr_frames += bytes([toc_byte]) + payload[i:i + sz]
        i += sz
    return amr_frames

def amr_to_wav(amr_data):
    with tempfile.NamedTemporaryFile(suffix='.amr', delete=False, mode='wb') as f:
        f.write(b'#!AMR\n')
        f.write(amr_data)
        amr_path = f.name
    wav_path = amr_path + '.wav'
    subprocess.run(
        ['ffmpeg', '-y', '-i', amr_path, '-ar', '16000', '-ac', '1', wav_path],
        capture_output=True, timeout=5)
    os.unlink(amr_path)
    if not os.path.exists(wav_path):
        return b""
    with open(wav_path, 'rb') as f:
        wav = f.read()
    os.unlink(wav_path)
    return wav

# =============================================================================
# TBCP (floor control)
# =============================================================================

def send_tbcp_release(phone_tbcp_addr):
    """Send Floor Release (subtype 5) + Floor Idle (subtype 6)."""
    if not phone_tbcp_addr:
        return
    for _ in range(3):
        for st, app in [
            (0x85, b'\x00\x00\x00\x00'),
            (0x85, struct.pack('>BBH', 0x65, 2, 0)),
            (0x86, b'\x00\x00\x00\x00'),
            (0x86, struct.pack('>BBH', 0x65, 2, 0)),
            (0x81, struct.pack('>BBH', 0x69, 2, 0)),
        ]:
            pkt = struct.pack('>BBH I 4s 4s', st, 0xCC, 3, SERVER_SSRC, b'PoC1', app)
            tbcp_sock.sendto(pkt, phone_tbcp_addr)
        time.sleep(0.1)
    log("MBCP", f"Floor Release+Idle (5×3 packets) -> {phone_tbcp_addr}")

def send_tbcp_taken(phone_tbcp_addr):
    """Send Talk Burst Taken (server is speaking)."""
    if not phone_tbcp_addr:
        return
    app_data = struct.pack('>BBH', 0x65, 2, 60)
    pkt = struct.pack('>BBH I 4s 4s', 0x81, 0xCC, 3, SERVER_SSRC, b'PoC1', app_data)
    tbcp_sock.sendto(pkt, phone_tbcp_addr)
    log("MBCP", f"Talk Burst Taken -> {phone_tbcp_addr}")

def send_mbcp_granted(phone_ip, phone_ssrc, req_id, reply_port=16385):
    app_data = struct.pack('>BBH', 101, 2, 60)
    pkt = struct.pack('>BBH I 4s 4s', 0x81, 0xCC, 3, SERVER_SSRC, b'PoC1', app_data)
    tbcp_sock.sendto(pkt, (phone_ip, reply_port))
    log("MBCP", f"Granted -> {phone_ip}:{reply_port} ssrc=0x{phone_ssrc:08x} req={req_id}")

# =============================================================================
# STT → LLM → TTS pipeline
# =============================================================================

def do_stt(audio):
    global server_speaking
    rtp_dest  = last_client.get('phone_rtp')
    tbcp_dest = last_client.get('phone_tbcp')

    # Claim floor and start hold music
    with lock:
        server_speaking = True
    if tbcp_dest:
        send_tbcp_taken(tbcp_dest)

    stop_hold   = threading.Event()
    hold_thread = None
    if rtp_dest and all_hold_music:
        hold_thread = threading.Thread(
            target=send_hold_music,
            args=(rtp_dest[0], rtp_dest[1], stop_hold),
            daemon=True)
        hold_thread.start()

    def finish():
        global server_speaking
        stop_hold.set()
        if hold_thread:
            hold_thread.join(timeout=1)
        with lock:
            server_speaking = False
        if tbcp_dest:
            send_tbcp_release(tbcp_dest)
        log("FLOOR", "Released — user can talk again")

    # --- STT ---
    with open("/tmp/last_burst.raw", "wb") as f:
        f.write(audio)
    wav = amr_to_wav(audio)
    if not wav:
        log("STT", "empty WAV")
        finish()
        return

    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        f.write(wav)
        wav_path = f.name

    text = ""

    # Try Groq Whisper API first (large-v3, high accuracy)
    if GROQ_API_KEY:
        try:
            with open(wav_path, 'rb') as audio_file:
                resp = requests.post(
                    GROQ_STT_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files={"file": ("audio.wav", audio_file, "audio/wav")},
                    data={"model": "whisper-large-v3", "language": WHISPER_LANG},
                    timeout=15)
            if resp.status_code == 200:
                text = resp.json().get("text", "").strip()
                log("STT", f"Groq [{WHISPER_LANG}]: '{text}'")
            else:
                log("STT", f"Groq error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log("STT", f"Groq failed ({e}), falling back to local whisper")
    else:
        log("STT", "No GROQ_API_KEY set, using local whisper")

    # Fallback: local whisper.cpp
    if not text and os.path.exists(WHISPER):
        result = subprocess.run(
            [WHISPER, '-m', MODEL, '-f', wav_path,
             '--max-len', '100', '-l', WHISPER_LANG],
            capture_output=True, timeout=30)
        out = result.stdout.decode(errors="ignore")
        lines = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            line = re.sub(r'^\[\d+:\d+:\d+\.\d+ --> \d+:\d+:\d+\.\d+\]\s*', '', line).strip()
            if line and not re.search(
                    r'\(C\)|BLANK_AUDIO|TV GELDERLAND|Ondertiteling|\[muziek\]',
                    line, re.I):
                lines.append(line)
        text = ' '.join(lines)
        log("STT", f"Local whisper [{WHISPER_LANG}]: '{text}'")

    os.unlink(wav_path)

    if not text:
        log("STT", "No text recognised")
        finish()
        return

    # --- LLM ---
    log("LLM", "Sending to DeepSeek...")
    reply = ask_deepseek(text)
    log("LLM", f"Reply: '{reply}'")

    # --- TTS ---
    tts_wav = '/tmp/tts_reply.wav'
    if not tts_to_wav(reply, tts_wav) or not rtp_dest:
        finish()
        return

    tts_frames = wav_to_amr_frames(tts_wav)
    if not tts_frames:
        log("TTS", "AMR encode failed")
        finish()
        return

    log("HOLD", "Stopping hold music for TTS playback")
    stop_hold.set()
    if hold_thread:
        hold_thread.join(timeout=1)

    log("TTS", f"Sending {len(tts_frames)} AMR frames to {rtp_dest[0]}:{rtp_dest[1]}")
    send_amr_frames(tts_frames, rtp_dest[0], rtp_dest[1], seq_start=3000, ts_start=0)
    log("TTS", "Done sending TTS")

    finish()

# =============================================================================
# SIP helpers
# =============================================================================

def patch_supported(msg):
    def replacer(m):
        val = m.group(1).strip()
        if 'pref' not in val:
            val += ', pref'
        return f'Supported: {val}'
    return re.sub(r'Supported:\s*(.+)', replacer, msg, flags=re.IGNORECASE)

def make_response(code, reason, msg, extra_headers="", body=""):
    via  = re.search(r'(Via:\s*.+)',     msg, re.I)
    frm  = re.search(r'(From:\s*.+)',    msg, re.I)
    to   = re.search(r'(To:\s*.+)',      msg, re.I)
    cid  = re.search(r'(Call-ID:\s*.+)', msg, re.I)
    cseq = re.search(r'(CSeq:\s*.+)',    msg, re.I)
    to_val = to.group(1).strip()
    if 'tag=' not in to_val:
        to_val += ';tag=pocserver01'
    return (
        f"SIP/2.0 {code} {reason}\r\n"
        f"{via.group(1).strip()}\r\n"
        f"{frm.group(1).strip()}\r\n"
        f"{to_val}\r\n"
        f"{cid.group(1).strip()}\r\n"
        f"{cseq.group(1).strip()}\r\n"
        f"{extra_headers}"
        f"Content-Length: {len(body.encode())}\r\n\r\n"
        f"{body}"
    )

def handle_invite(sip_sock, addr, msg):
    log("INVITE", f"Handling INVITE from {addr}")
    sip_sock.sendto(make_response(100, "Trying", msg).encode(), addr)
    log_sip(">>>", addr, "100 Trying")
    sdp = (
        f"v=0\r\n"
        f"o=poc-server 1 1 IN IP4 {MY_IP}\r\n"
        f"s=-\r\n"
        f"c=IN IP4 {MY_IP}\r\n"
        f"t=0 0\r\n"
        f"m=audio {RTP_PORT} RTP/AVP 106\r\n"
        f"a=sendrecv\r\n"
        f"a=rtpmap:106 AMR/8000\r\n"
        f"a=ptime:160\r\n"
        f"a=fmtp:106 octet-align=1; mode-set=0,1,2\r\n"
        f"m=application {TBCP_PORT} udp TBCP\r\n"
    )
    extra = (
        f"Contact: <sip:ai@{MY_IP}:5060>\r\n"
        f"Content-Type: application/sdp\r\n"
        f"Allow: INVITE, ACK, BYE, CANCEL, OPTIONS, NOTIFY\r\n"
    )
    resp = make_response(200, "OK", msg, extra_headers=extra, body=sdp)
    sip_sock.sendto(resp.encode(), addr)
    log_sip(">>>", addr, resp)

# =============================================================================
# BACKGROUND LOOPS
# =============================================================================

def tbcp_loop():
    global granted
    log("TBCP", f"Listening on :{TBCP_PORT}")
    while True:
        try:
            data, addr = tbcp_sock.recvfrom(4096)
            log("TBCP", f"Packet from {addr[0]}:{addr[1]} len={len(data)}")
            last_client['phone_tbcp'] = addr
            if len(data) >= 16:
                phone_ssrc = struct.unpack('>I', data[4:8])[0]
                primitive  = data[12]
                req_id     = struct.unpack('>H', data[14:16])[0]
                log("TBCP", f"prim=0x{primitive:02x} ssrc=0x{phone_ssrc:08x} req={req_id} from={addr}")
                last_client['phone_ssrc'] = phone_ssrc

                if primitive == 0x66:   # Floor Request
                    with lock:
                        granted = True
                    send_mbcp_granted(addr[0], phone_ssrc, req_id, addr[1])

                elif primitive == 0x00:  # Idle keepalive
                    with lock:
                        speaking = server_speaking
                    if not speaking:
                        for st in [0x85, 0x86]:
                            pkt = struct.pack('>BBH I 4s 4s',
                                              st, 0xCC, 3, SERVER_SSRC,
                                              b'PoC1', b'\x00\x00\x00\x00')
                            tbcp_sock.sendto(pkt, addr)
                        log("TBCP", "Replied to keepalive with Release+Idle")
        except socket.timeout:
            pass

def rtp_loop():
    global burst_audio, granted
    log("RTP", f"Listening on :{RTP_PORT}")
    while True:
        try:
            data, addr = rtp_sock.recvfrom(4096)
            with lock:
                last_client['phone_rtp'] = addr
                if granted:
                    burst_audio += parse_amr_from_rtp(data[12:])
                    if len(burst_audio) % 500 < 50:
                        log("RTP", f"burst={len(burst_audio)} bytes from {addr}")
        except socket.timeout:
            with lock:
                audio      = burst_audio
                burst_audio = b""
                if audio:
                    granted = False
            if audio:
                log("RTP", f"PTT released — {len(audio)} bytes → STT pipeline")
                threading.Thread(target=do_stt, args=(audio,), daemon=True).start()

# =============================================================================
# MAIN SIP PROXY LOOP
# =============================================================================

def proxy():
    threading.Thread(target=tbcp_loop, daemon=True).start()
    threading.Thread(target=rtp_loop,  daemon=True).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LISTEN_PORT))

    log("PROXY", f"Listening on 0.0.0.0:{LISTEN_PORT}")
    log("PROXY", f"Asterisk at {ASTERISK_IP}:{ASTERISK_PORT}")
    log("PROXY", f"RTP :{RTP_PORT}  TBCP :{TBCP_PORT}")
    log("PROXY", f"Language: {LANGUAGE} | STT lang: {WHISPER_LANG} | TTS voice: {TTS_VOICE}")

    while True:
        data, addr = sock.recvfrom(65535)
        msg        = data.decode(errors='ignore')
        first_line = msg.split('\r\n')[0]
        log_sip("<<<", addr, first_line)

        if addr[0] == ASTERISK_IP:
            phone_sip = last_client.get('phone_sip')
            if phone_sip:
                log("PROXY", f"Asterisk → Phone {phone_sip} | {first_line}")
                sock.sendto(patch_supported(msg).encode(), phone_sip)
            else:
                log("PROXY", f"Asterisk resp but no phone_sip stored — dropping: {first_line}")

        elif "symbian" in msg:
            last_client['phone_sip'] = addr
            log("PROXY", f"Phone SIP addr stored: {addr}")

            if   'INVITE'    in first_line:
                handle_invite(sock, addr, msg)
            elif 'REGISTER'  in first_line:
                log("PROXY", "REGISTER → Asterisk")
                sock.sendto(data, (ASTERISK_IP, ASTERISK_PORT))
            elif 'PUBLISH'   in first_line and 'poc-settings' in msg:
                sock.sendto(
                    make_response(200, "OK", msg,
                                  extra_headers="Expires: 3600\r\n").encode(), addr)
            elif 'SUBSCRIBE' in first_line:
                sock.sendto(
                    make_response(200, "OK", msg,
                                  extra_headers="Expires: 3600\r\n").encode(), addr)
            elif 'BYE'       in first_line:
                sock.sendto(make_response(200, "OK", msg).encode(), addr)
                conversation_history.clear()
                log("PROXY", "BYE → 200 OK, conversation history cleared")
            elif 'ACK' in first_line or 'CANCEL' in first_line:
                pass
            else:
                sock.sendto(data, (ASTERISK_IP, ASTERISK_PORT))

        else:
            log("UNKNOWN", f"{addr[0]}:{addr[1]} | {first_line}")

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    log("START", "=" * 60)
    log("START", "PoC AI Proxy starting up")
    log("START", f"Language profile: {LANGUAGE.upper()} "
                 f"(STT={WHISPER_LANG}, TTS={TTS_VOICE})")
    log("START", "=" * 60)
    load_hold_music()
    proxy()
