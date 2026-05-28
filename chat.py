"""
Serverless function para Vercel.
Endpoint: POST /api/chat
Llama a MiMo API (Xiaomi) compatible con formato Anthropic.

Variables de entorno (configurar en Vercel):
  MIMO_API_KEY    - Tu API key de platform.xiaomimimo.com
  MODEL           - Modelo (default: mimo-v2.5-pro)
  RATE_LIMIT_PER_MIN - Mensajes/minuto por IP (default: 20)
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import time
import urllib.request
import urllib.error
from collections import defaultdict, deque
from pathlib import Path

MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MODEL = os.environ.get("MODEL", "mimo-v2.5-pro")
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8000"))

MIMO_URL = "https://api.xiaomimimo.com/anthropic/v1/messages"

# Cargar system prompt una vez por cold start
_SYSTEM_PROMPT = None

def get_system_prompt():
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        # En Vercel, el archivo vive junto a la function
        candidates = [
            Path(__file__).parent / "system_prompt.txt",
            Path(__file__).parent.parent / "system_prompt.txt",
            Path("/var/task/api/system_prompt.txt"),
        ]
        for p in candidates:
            if p.exists():
                _SYSTEM_PROMPT = p.read_text(encoding='utf-8')
                break
        if _SYSTEM_PROMPT is None:
            _SYSTEM_PROMPT = "Eres un coach de Leyes Biologicas. (system_prompt.txt no encontrado)"
    return _SYSTEM_PROMPT


# Rate limiting en memoria (se pierde entre cold starts, suficiente para empezar)
_rate_buckets = defaultdict(lambda: deque(maxlen=RATE_LIMIT))


def check_rate_limit(ip):
    now = time.time()
    bucket = _rate_buckets[ip]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT:
        return False
    bucket.append(now)
    return True


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
            self._send_error(500, "MIMO_API_KEY no configurada en el servidor")
            return

        # Rate limit
        client_ip = self.headers.get('x-forwarded-for', 'unknown').split(',')[0].strip()
        if not check_rate_limit(client_ip):
            self._send_error(429, "Demasiadas peticiones. Intenta en un minuto.")
            return

        # Leer body
        try:
            length = int(self.headers.get('content-length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            messages = data.get('messages', [])
            if not messages:
                self._send_error(400, "Falta el campo messages")
                return
        except (ValueError, json.JSONDecodeError) as e:
            self._send_error(400, f"Body inválido: {e}")
            return

        # Construir payload para MiMo
        payload = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": get_system_prompt(),
            "messages": messages,
            "stream": True,
        }

        # Llamar a MiMo y hacer stream a la respuesta
        req = urllib.request.Request(
            MIMO_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MIMO_API_KEY}",
            },
            method="POST",
        )

        try:
            # Vercel limita stream pero podemos enviar respuesta progresiva
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self._set_cors()
            self.end_headers()

            with urllib.request.urlopen(req, timeout=110) as resp:
                for line_bytes in resp:
                    line = line_bytes.decode('utf-8', errors='replace').strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        try:
                            ev = json.loads(raw)
                            if ev.get("type") == "content_block_delta":
                                text = ev.get("delta", {}).get("text", "")
                                if text:
                                    out = json.dumps({"chunk": text}, ensure_ascii=False)
                                    self.wfile.write(f"data: {out}\n\n".encode('utf-8'))
                                    try:
                                        self.wfile.flush()
                                    except Exception:
                                        pass
                            elif ev.get("type") == "message_stop":
                                self.wfile.write(b"data: [DONE]\n\n")
                        except json.JSONDecodeError:
                            pass
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            msg = json.dumps({"error": f"MiMo {e.code}: {err_body}"}, ensure_ascii=False)
            try:
                self.wfile.write(f"data: {msg}\n\n".encode('utf-8'))
            except Exception:
                pass
        except Exception as e:
            msg = json.dumps({"error": f"Error: {str(e)}"}, ensure_ascii=False)
            try:
                self.wfile.write(f"data: {msg}\n\n".encode('utf-8'))
            except Exception:
                pass

    def do_GET(self):
        # Health check
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({
            "ok": True,
            "model": MODEL,
            "has_api_key": bool(MIMO_API_KEY),
            "system_prompt_loaded": bool(get_system_prompt()),
        }).encode('utf-8'))

    def _send_error(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode('utf-8'))
