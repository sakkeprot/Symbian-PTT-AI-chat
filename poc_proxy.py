#!/usr/bin/env python3
"""
PoC (Push-to-Talk over Cellular) AI Proxy
==========================================
Intercepts PTT calls from a PoC-enabled phone, performs speech-to-text,
sends the transcript to DeepSeek, and speaks the reply back over the
radio channel using TTS.

Protocol stack:
  SIP  — registration & call signalling
  RTP  — AMR-NB audio transport
  TBCP — OMA PoC floor control (talk burst)

Edit config.py before running.
"""

import os, re, socket, struct, subprocess, sys, tempfile, threading, time, random
import requests
from datetime import datetime

# Local config — edit config.py, not this file
from config import (
    LANGUAGE, LANGUAGE_PROFILES,
    MY_IP, PHONE_IP,
    LISTEN_PORT, ASTERISK_IP, ASTERISK_PORT,
    RTP_PORT, TBCP_PORT, SERVER_SSRC,
    DEEPSEEK_API_KEY, GROQ_API_KEY,
    WHISPER, MODEL, HOLD_MUSIC_FILES,
    LOG_FILE,
)

# ---------------------------------------------------------------------------
# Resolve language profile
# ---------------------------------------------------------------------------
def _resolve_language():
    key = LANGUAGE.lower().strip()
    if key not in LANGUAGE_PROFILES:
        raise ValueError(
            f"Unsupported LANGUAGE '{LANGUAGE}' in config.py. "
            f"Choose from: {', '.join(LANGUAGE_PROFILES)}"
        )
    return LANGUAGE_PROFILES[key]

WHISPER_LANG, TTS_VOICE, SYSTEM_PROMPT = _resolve_language()

# API endpoints
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# AMR-NB frame sizes (RFC 3267)
FT_SPEECH_SIZES = {0: 12, 1: 13, 2: 15, 3: 17, 4: 19, 5: 20, 6: 26, 7: 31, 8: 5}

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
burst_audio          = b""
granted              = False
server_speaking      = False
lock                 = threading.Lock()
last_client          = {}
conversation_history = []   # cleared on BYE
all_hold_music       = []

# Sockets
rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
rtp_sock.bind(("0.0.0.0", RTP_PORT))
rtp_sock.settimeout(1)

tbcp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
tbcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
tbcp_sock.bind(("0.0.0.0", TBCP_PORT))
tbcp_sock.settimeout(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(tag, msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    line = f"[{ts}] [{tag}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def log_sip(direction, addr, msg):
    first = msg.split('\r\n')[0] if '\r\n' in msg else msg.split('\n')[0]
    log("SIP",      f"{direction} {addr[0]}:{addr[1]} | {first}")
    log("SIP-FULL", f"{direction} {addr[0]}:{addr[1]}\n{msg}\n{'='*60}")

# ---------------------------------------------------------------------------
# Hold music
# ---------------------------------------------------------------------------
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
        frames, pos = [], 6
        while pos < len(amr):
            fh = amr[pos]; ft = (fh >> 3) & 0xF
            sz = FT_SPEECH_SIZES.get(ft, 0)
            if sz == 0: pos += 1; continue
            frames.append(amr[pos:pos + 1 + sz])
            pos += 1 + sz
        if frames:
            all_hold_music.append(frames)
            log("HOLD", f"Loaded {len(frames)} frames from {os.path.basename(path)}")
    log("HOLD", f"Total {len(all_hold_music)} track(s) loaded")

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
def ask_deepseek(text):
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
               "Content-Type": "application/json"}
    conversation_history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history
    try:
        r     = requests.post(DEEPSEEK_URL, headers=headers,
                              json={"model": "deepseek-chat", "messages": messages},
                              timeout=15)
        reply = r.json()["choices"][0]["message"]["content"].strip()
        conversation_history.append({"role": "assistant", "content": reply})
        log("LLM", f"History: {len(conversation_history)} messages")
        return reply
    except Exception as e:
        log("LLM", f"ERR: {e}")
        conversation_history.pop()
        return "Sorry, an error occurred."

# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
def tts_to_wav(text, wav_path):
    """edge-tts → espeak-ng fallback. Prepends 1 s silence."""
    raw_wav = wav_path + '.raw.wav'
    try:
        mp3_path = wav_path + '.mp3'
        result = subprocess.run(
            ['edge-tts', '--voice', TTS_VOICE, '--text', text,
             '--write-media', mp3_path],
            capture_output=True, timeout=15)
        if os.path.exists(mp3_path):
            subprocess.run(['ffmpeg', '-y', '-i', mp3_path,
                            '-ar', '8000', '-ac', '1', raw_wav],
                           capture_output=True, timeout=10)
            os.unlink(mp3_path)
        if not os.path.exists(raw_wav):
            raise Exception(result.stderr.decode(errors='ignore')[:200])
        log("TTS", f"edge-tts OK ({TTS_VOICE})")
    except Exception as e:
        log("TTS", f"edge-tts failed ({e}), using espeak-ng")
        subprocess.run(['espeak-ng', '-v', WHISPER_LANG, '-s', '150',
                        '-w', raw_wav, text], capture_output=True)

    if not os.path.exists(raw_wav):
        return False

    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', 'anullsrc=r=8000:cl=mono', '-i', raw_wav,
        '-filter_complex', '[0]atrim=0:1[s];[s][1]concat=n=2:v=0:a=1',
        '-ar', '8000', '-ac', '1', wav_path
    ], capture_output=True, timeout=10)
    os.unlink(raw_wav)
    return os.path.exists(wav_path)

# ---------------------------------------------------------------------------
# RTP / AMR helpers
# ---------------------------------------------------------------------------
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
    frames, pos = [], 6
    while pos < len(amr):
        fh = amr[pos]; ft = (fh >> 3) & 0xF
        sz = FT_SPEECH_SIZES.get(ft, 0)
        if sz == 0: pos += 1; continue
        frames.append(amr[pos:pos + 1 + sz])
        pos += 1 + sz
    return frames

def send_amr_frames(frames, dest_ip, dest_port,
                    stop_event=None, seq_start=1000, ts_start=0):
    seq, ts = seq_start, ts_start
    for i in range(0, len(frames), 8):
        if stop_event and stop_event.is_set():
            return (seq, ts)
        batch   = frames[i:i + 8]
        toc     = b"".join(
            bytes([fr[0] | 0x80]) if j < len(batch) - 1 else bytes([fr[0] & 0x7F])
            for j, fr in enumerate(batch))
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
        log("HOLD", "No tracks loaded"); return
    frames = random.choice(all_hold_music)
    log("HOLD", f"{len(frames)} frames → {dest_ip}:{dest_port}")
    seq, ts = 2000, 0
    while not stop_event.is_set():
        seq, ts = send_amr_frames(frames, dest_ip, dest_port, stop_event, seq, ts)
    log("HOLD", "Stopped")

def parse_amr_from_rtp(payload):
    amr, i, toc = b"", 1, []
    while i < len(payload):
        b = payload[i]; i += 1
        toc.append(((b >> 3) & 0xF, b & 0x7F))
        if not (b >> 7): break
    for ft, toc_byte in toc:
        sz   = FT_SPEECH_SIZES.get(ft, 0)
        amr += bytes([toc_byte]) + payload[i:i + sz]
        i   += sz
    return amr

def amr_to_wav(amr_data):
    with tempfile.NamedTemporaryFile(suffix='.amr', delete=False, mode='wb') as f:
        f.write(b'#!AMR\n'); f.write(amr_data); amr_path = f.name
    wav_path = amr_path + '.wav'
    subprocess.run(['ffmpeg', '-y', '-i', amr_path,
                    '-ar', '16000', '-ac', '1', wav_path],
                   capture_output=True, timeout=5)
    os.unlink(amr_path)
    if not os.path.exists(wav_path): return b""
    with open(wav_path, 'rb') as f: wav = f.read()
    os.unlink(wav_path)
    return wav

# ---------------------------------------------------------------------------
# TBCP (floor control)
# ---------------------------------------------------------------------------
def send_tbcp_taken(addr):
    if not addr: return
    app = struct.pack('>BBH', 0x65, 2, 60)
    tbcp_sock.sendto(
        struct.pack('>BBH I 4s 4s', 0x81, 0xCC, 3, SERVER_SSRC, b'PoC1', app), addr)
    log("TBCP", f"Taken → {addr}")

def send_tbcp_release(addr):
    if not addr: return
    for _ in range(3):
        for st, app in [
            (0x85, b'\x00\x00\x00\x00'),
            (0x85, struct.pack('>BBH', 0x65, 2, 0)),
            (0x86, b'\x00\x00\x00\x00'),
            (0x86, struct.pack('>BBH', 0x65, 2, 0)),
            (0x81, struct.pack('>BBH', 0x69, 2, 0)),
        ]:
            tbcp_sock.sendto(
                struct.pack('>BBH I 4s 4s', st, 0xCC, 3, SERVER_SSRC, b'PoC1', app), addr)
        time.sleep(0.1)
    log("TBCP", f"Release+Idle → {addr}")

def send_mbcp_granted(phone_ip, phone_ssrc, req_id, port=16385):
    app = struct.pack('>BBH', 101, 2, 60)
    tbcp_sock.sendto(
        struct.pack('>BBH I 4s 4s', 0x81, 0xCC, 3, SERVER_SSRC, b'PoC1', app),
        (phone_ip, port))
    log("TBCP", f"Granted → {phone_ip}:{port} ssrc=0x{phone_ssrc:08x} req={req_id}")

# ---------------------------------------------------------------------------
# STT → LLM → TTS pipeline
# ---------------------------------------------------------------------------
def do_stt(audio):
    global server_speaking
    rtp_dest  = last_client.get('phone_rtp')
    tbcp_dest = last_client.get('phone_tbcp')

    with lock: server_speaking = True
    if tbcp_dest: send_tbcp_taken(tbcp_dest)

    stop_hold   = threading.Event()
    hold_thread = None
    if rtp_dest and all_hold_music:
        hold_thread = threading.Thread(
            target=send_hold_music,
            args=(rtp_dest[0], rtp_dest[1], stop_hold), daemon=True)
        hold_thread.start()

    def finish():
        global server_speaking
        stop_hold.set()
        if hold_thread: hold_thread.join(timeout=1)
        with lock: server_speaking = False
        if tbcp_dest: send_tbcp_release(tbcp_dest)
        log("FLOOR", "Released — user can talk again")

    # STT
    wav = amr_to_wav(audio)
    if not wav: log("STT", "empty WAV"); finish(); return

    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        f.write(wav); wav_path = f.name

    text = ""

    # Groq Whisper (preferred)
    if GROQ_API_KEY:
        try:
            with open(wav_path, 'rb') as af:
                resp = requests.post(
                    GROQ_STT_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files={"file": ("audio.wav", af, "audio/wav")},
                    data={"model": "whisper-large-v3", "language": WHISPER_LANG},
                    timeout=15)
            if resp.status_code == 200:
                text = resp.json().get("text", "").strip()
                log("STT", f"Groq [{WHISPER_LANG}]: '{text}'")
            else:
                log("STT", f"Groq {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            log("STT", f"Groq failed ({e})")
    else:
        log("STT", "No GROQ_API_KEY — using local whisper")

    # Local whisper.cpp fallback
    if not text and os.path.exists(WHISPER):
        result = subprocess.run(
            [WHISPER, '-m', MODEL, '-f', wav_path,
             '--max-len', '100', '-l', WHISPER_LANG],
            capture_output=True, timeout=30)
        lines = []
        for line in result.stdout.decode(errors="ignore").splitlines():
            line = re.sub(r'^\[\d+:\d+:\d+\.\d+ --> \d+:\d+:\d+\.\d+\]\s*', '',
                          line.strip()).strip()
            if line and not re.search(
                    r'\(C\)|BLANK_AUDIO|TV GELDERLAND|Ondertiteling|\[muziek\]',
                    line, re.I):
                lines.append(line)
        text = ' '.join(lines)
        log("STT", f"Local [{WHISPER_LANG}]: '{text}'")

    os.unlink(wav_path)
    if not text: log("STT", "No text recognised"); finish(); return

    # LLM
    log("LLM", "Querying DeepSeek…")
    reply = ask_deepseek(text)
    log("LLM", f"Reply: '{reply}'")

    # TTS
    tts_wav = '/tmp/tts_reply.wav'
    if not tts_to_wav(reply, tts_wav) or not rtp_dest:
        finish(); return

    tts_frames = wav_to_amr_frames(tts_wav)
    if not tts_frames: log("TTS", "AMR encode failed"); finish(); return

    stop_hold.set()
    if hold_thread: hold_thread.join(timeout=1)

    log("TTS", f"Sending {len(tts_frames)} frames → {rtp_dest[0]}:{rtp_dest[1]}")
    send_amr_frames(tts_frames, rtp_dest[0], rtp_dest[1], seq_start=3000, ts_start=0)
    log("TTS", "Done")
    finish()

# ---------------------------------------------------------------------------
# SIP helpers
# ---------------------------------------------------------------------------
def patch_supported(msg):
    def fix(m):
        v = m.group(1).strip()
        return f'Supported: {v}, pref' if 'pref' not in v else f'Supported: {v}'
    return re.sub(r'Supported:\s*(.+)', fix, msg, flags=re.IGNORECASE)

def make_response(code, reason, msg, extra_headers="", body=""):
    def hdr(pattern): return re.search(pattern, msg, re.I).group(1).strip()
    to_val = hdr(r'(To:\s*.+)')
    if 'tag=' not in to_val: to_val += ';tag=pocserver01'
    return (
        f"SIP/2.0 {code} {reason}\r\n"
        f"{hdr(r'(Via:\\s*.+)')}\r\n"
        f"{hdr(r'(From:\\s*.+)')}\r\n"
        f"{to_val}\r\n"
        f"{hdr(r'(Call-ID:\\s*.+)')}\r\n"
        f"{hdr(r'(CSeq:\\s*.+)')}\r\n"
        f"{extra_headers}"
        f"Content-Length: {len(body.encode())}\r\n\r\n"
        f"{body}"
    )

def handle_invite(sock, addr, msg):
    log("SIP", f"INVITE from {addr}")
    sock.sendto(make_response(100, "Trying", msg).encode(), addr)
    sdp = (
        f"v=0\r\no=poc-server 1 1 IN IP4 {MY_IP}\r\ns=-\r\n"
        f"c=IN IP4 {MY_IP}\r\nt=0 0\r\n"
        f"m=audio {RTP_PORT} RTP/AVP 106\r\n"
        f"a=sendrecv\r\na=rtpmap:106 AMR/8000\r\na=ptime:160\r\n"
        f"a=fmtp:106 octet-align=1; mode-set=0,1,2\r\n"
        f"m=application {TBCP_PORT} udp TBCP\r\n"
    )
    extra = (
        f"Contact: <sip:ai@{MY_IP}:5060>\r\n"
        f"Content-Type: application/sdp\r\n"
        f"Allow: INVITE, ACK, BYE, CANCEL, OPTIONS, NOTIFY\r\n"
    )
    sock.sendto(make_response(200, "OK", msg, extra, sdp).encode(), addr)

# ---------------------------------------------------------------------------
# Background loops
# ---------------------------------------------------------------------------
def tbcp_loop():
    global granted
    log("TBCP", f"Listening on :{TBCP_PORT}")
    while True:
        try:
            data, addr = tbcp_sock.recvfrom(4096)
            last_client['phone_tbcp'] = addr
            if len(data) >= 16:
                phone_ssrc = struct.unpack('>I', data[4:8])[0]
                primitive  = data[12]
                req_id     = struct.unpack('>H', data[14:16])[0]
                log("TBCP", f"prim=0x{primitive:02x} ssrc=0x{phone_ssrc:08x} req={req_id}")
                last_client['phone_ssrc'] = phone_ssrc
                if primitive == 0x66:   # Floor Request
                    with lock: granted = True
                    send_mbcp_granted(addr[0], phone_ssrc, req_id, addr[1])
                elif primitive == 0x00:  # Keepalive
                    with lock: speaking = server_speaking
                    if not speaking:
                        for st in [0x85, 0x86]:
                            tbcp_sock.sendto(
                                struct.pack('>BBH I 4s 4s', st, 0xCC, 3,
                                            SERVER_SSRC, b'PoC1', b'\x00\x00\x00\x00'),
                                addr)
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
        except socket.timeout:
            with lock:
                audio = burst_audio; burst_audio = b""
                if audio: granted = False
            if audio:
                log("RTP", f"PTT released — {len(audio)} B → STT")
                threading.Thread(target=do_stt, args=(audio,), daemon=True).start()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def proxy():
    threading.Thread(target=tbcp_loop, daemon=True).start()
    threading.Thread(target=rtp_loop,  daemon=True).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LISTEN_PORT))

    log("PROXY", f"Listening on 0.0.0.0:{LISTEN_PORT}")
    log("PROXY", f"Asterisk: {ASTERISK_IP}:{ASTERISK_PORT}")
    log("PROXY", f"Language: {LANGUAGE.upper()}  STT={WHISPER_LANG}  TTS={TTS_VOICE}")

    while True:
        data, addr = sock.recvfrom(65535)
        msg        = data.decode(errors='ignore')
        first      = msg.split('\r\n')[0]
        log_sip("<<<", addr, first)

        if addr[0] == ASTERISK_IP:
            ps = last_client.get('phone_sip')
            if ps: sock.sendto(patch_supported(msg).encode(), ps)
            else:  log("PROXY", f"No phone_sip — dropping: {first}")

        elif "symbian" in msg:
            last_client['phone_sip'] = addr
            if   'INVITE'    in first: handle_invite(sock, addr, msg)
            elif 'REGISTER'  in first: sock.sendto(data, (ASTERISK_IP, ASTERISK_PORT))
            elif 'PUBLISH'   in first and 'poc-settings' in msg:
                sock.sendto(make_response(200,"OK",msg,"Expires: 3600\r\n").encode(), addr)
            elif 'SUBSCRIBE' in first:
                sock.sendto(make_response(200,"OK",msg,"Expires: 3600\r\n").encode(), addr)
            elif 'BYE'       in first:
                sock.sendto(make_response(200,"OK",msg).encode(), addr)
                conversation_history.clear()
                log("PROXY", "BYE — conversation history cleared")
            elif first.startswith(('ACK','CANCEL')):
                pass
            else:
                sock.sendto(data, (ASTERISK_IP, ASTERISK_PORT))
        else:
            log("UNKNOWN", f"{addr[0]}:{addr[1]} | {first}")

if __name__ == "__main__":
    log("START", "=" * 60)
    log("START", f"PoC AI Proxy  |  lang={LANGUAGE}  tts={TTS_VOICE}")
    log("START", "=" * 60)
    load_hold_music()
    proxy()
