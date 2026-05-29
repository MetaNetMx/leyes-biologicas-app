"""
Serverless function para generar audio TTS con MiMo.
Endpoint: POST /api/tts
Body: { "text": "texto a sintetizar", "voice_style": "opcional" }
Response: audio/wav
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import base64
import urllib.request
import urllib.error
import hashlib
import time
from collections import defaultdict, deque

MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
TTS_URL = "https://api.xiaomimimo.com/v1/chat/completions"

# Rate limit más estricto para TTS (es costoso)
TTS_RATE_LIMIT = int(os.environ.get("TTS_RATE_LIMIT_PER_HOUR", "10"))
_tts_buckets = defaultdict(lambda: deque(maxlen=TTS_RATE_LIMIT))


def check_tts_rate(ip):
    now = time.time()
    bucket = _tts_buckets[ip]
    while bucket and bucket[0] < now - 3600:
        bucket.popleft()
    if len(bucket) >= TTS_RATE_LIMIT:
        return False
    bucket.append(now)
    return True


# Estilo de voz por defecto para meditación
DEFAULT_VOICE_STYLE = (
    "Voz femenina joven en español neutral, cálida y pausada, "
    "tono de meditación guiada. Ritmo lento y relajante, "
    "respiración natural, articulación clara, susurro suave en pausas."
)


class handler(BaseHTTPRequestHandler):

    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors()
        self.end_headers()

    def do_POST(self):
        if not MIMO_API_KEY:
            self._error(500, "MIMO_API_KEY no configurada")
            return

        client_ip = self.headers.get('x-forwarded-for', 'unknown').split(',')[0].strip()
        if not check_tts_rate(client_ip):
            self._error(429, "Demasiadas solicitudes de audio. Intenta en una hora.")
            return

        try:
            length = int(self.headers.get('content-length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            texto = (data.get('text') or '').strip()
            voice_style = data.get('voice_style') or DEFAULT_VOICE_STYLE
            if not texto:
                self._error(400, "Falta el campo text")
                return
            # MiMo TTS tiene un límite de longitud razonable; cortar si es excesivo
            if len(texto) > 8000:
                texto = texto[:8000]
        except (ValueError, json.JSONDecodeError) as e:
            self._error(400, f"Body inválido: {e}")
            return

        payload = {
            "model": "mimo-v2.5-tts-voicedesign",
            "messages": [
                {"role": "user", "content": voice_style},
                {"role": "assistant", "content": texto}
            ],
            "audio": {
                "format": "wav",
                "optimize_text_preview": True
            }
        }

        req = urllib.request.Request(
            TTS_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MIMO_API_KEY}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=110) as resp:
                response_data = json.loads(resp.read().decode('utf-8'))

            # Extraer audio base64
            try:
                audio_b64 = response_data['choices'][0]['message']['audio']['data']
            except (KeyError, IndexError):
                self._error(502, f"Respuesta de TTS inesperada: {json.dumps(response_data)[:300]}")
                return

            audio_bytes = base64.b64decode(audio_b64)

            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio_bytes)))
            self.send_header("Content-Disposition", 'attachment; filename="meditacion.wav"')
            self._set_cors()
            self.end_headers()
            self.wfile.write(audio_bytes)

        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')[:500]
            self._error(502, f"MiMo TTS {e.code}: {err_body}")
        except Exception as e:
            self._error(500, f"Error: {str(e)}")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({
            "endpoint": "/api/tts",
            "method": "POST",
            "body": {"text": "...", "voice_style": "(opcional)"},
            "rate_limit_per_hour": TTS_RATE_LIMIT,
        }).encode('utf-8'))

    def _error(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode('utf-8'))
