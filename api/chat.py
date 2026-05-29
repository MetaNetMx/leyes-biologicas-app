"""
Serverless function para Vercel.
Endpoint: POST /api/chat
Llama a MiMo API (formato Anthropic) y guarda conversaciones en Supabase.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import time
import hashlib
import urllib.request
import urllib.error
from collections import defaultdict, deque
from pathlib import Path

MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MODEL = os.environ.get("MODEL", "mimo-v2.5-pro")
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "20"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8000"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

MIMO_URL = "https://api.xiaomimimo.com/anthropic/v1/messages"

_SYSTEM_PROMPT = None

def get_system_prompt():
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
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
            _SYSTEM_PROMPT = "Eres un coach de Leyes Biologicas."
    return _SYSTEM_PROMPT


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


def guardar_conversacion(session_id, mensajes, ip_hash, user_agent, respuesta_final):
    """UPSERT a Supabase. Falla silenciosamente si no hay creds."""
    if not (SUPABASE_URL and SUPABASE_KEY and session_id):
        return

    # Extraer info útil de la conversación
    sintoma_inicial = ""
    for m in mensajes:
        if m.get("role") == "user":
            sintoma_inicial = m.get("content", "")[:500]
            break

    # Detectar si hubo meditación
    genero_meditacion = False
    analisis = None
    try:
        # Buscar en última respuesta del assistant
        if respuesta_final:
            r_low = respuesta_final.lower()
            if "meditacion" in r_low or "meditación" in r_low or '"meditacion"' in r_low:
                genero_meditacion = True
            # Intentar extraer análisis si está en JSON
            inicio = respuesta_final.find('"analisis"')
            if inicio > 0:
                try:
                    j = json.loads(respuesta_final[respuesta_final.find('{'):respuesta_final.rfind('}')+1])
                    if 'analisis' in j:
                        analisis = j['analisis']
                except Exception:
                    pass
    except Exception:
        pass

    # Agregar respuesta final al historial
    mensajes_completos = list(mensajes)
    if respuesta_final:
        mensajes_completos.append({"role": "assistant", "content": respuesta_final[:30000]})

    payload = {
        "session_id": session_id,
        "sintoma_inicial": sintoma_inicial,
        "mensajes": mensajes_completos,
        "analisis": analisis,
        "num_mensajes": len(mensajes_completos),
        "genero_meditacion": genero_meditacion,
        "ip_hash": ip_hash,
        "user_agent": (user_agent or "")[:300],
    }

    # UPSERT por session_id (necesita unique constraint, hacemos delete + insert manual)
    try:
        # Primero borrar existente
        del_url = f"{SUPABASE_URL}/rest/v1/lb_conversaciones?session_id=eq.{session_id}"
        req_del = urllib.request.Request(del_url, method="DELETE", headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Prefer": "return=minimal",
        })
        try:
            urllib.request.urlopen(req_del, timeout=4)
        except Exception:
            pass

        # Insertar nuevo
        ins_url = f"{SUPABASE_URL}/rest/v1/lb_conversaciones"
        req_ins = urllib.request.Request(
            ins_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            method="POST",
        )
        urllib.request.urlopen(req_ins, timeout=4)
    except Exception as e:
        # No bloqueamos al usuario por esto
        print(f"supabase write error: {e}")


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
            self._send_error(500, "MIMO_API_KEY no configurada")
            return

        client_ip = self.headers.get('x-forwarded-for', 'unknown').split(',')[0].strip()
        user_agent = self.headers.get('user-agent', '')
        ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]

        if not check_rate_limit(client_ip):
            self._send_error(429, "Demasiadas peticiones. Intenta en un minuto.")
            return

        try:
            length = int(self.headers.get('content-length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = json.loads(body)
            messages = data.get('messages', [])
            session_id = data.get('session_id', '')
            if not messages:
                self._send_error(400, "Falta el campo messages")
                return
        except (ValueError, json.JSONDecodeError) as e:
            self._send_error(400, f"Body inválido: {e}")
            return

        payload = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": get_system_prompt(),
            "messages": messages,
            "stream": True,
        }

        req = urllib.request.Request(
            MIMO_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MIMO_API_KEY}",
            },
            method="POST",
        )

        respuesta_acumulada = ""

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self._set_cors()
            self.end_headers()

            with urllib.request.urlopen(req, timeout=110) as resp:
                for line_bytes in resp:
                    line = line_bytes.decode('utf-8', errors='replace').strip()
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    try:
                        ev = json.loads(raw)
                        if ev.get("type") == "content_block_delta":
                            text = ev.get("delta", {}).get("text", "")
                            if text:
                                respuesta_acumulada += text
                                out = json.dumps({"chunk": text}, ensure_ascii=False)
                                self.wfile.write(f"data: {out}\n\n".encode('utf-8'))
                                try: self.wfile.flush()
                                except Exception: pass
                        elif ev.get("type") == "message_stop":
                            self.wfile.write(b"data: [DONE]\n\n")
                    except json.JSONDecodeError:
                        pass
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            msg = json.dumps({"error": f"MiMo {e.code}: {err_body}"}, ensure_ascii=False)
            try: self.wfile.write(f"data: {msg}\n\n".encode('utf-8'))
            except Exception: pass
        except Exception as e:
            msg = json.dumps({"error": f"Error: {str(e)}"}, ensure_ascii=False)
            try: self.wfile.write(f"data: {msg}\n\n".encode('utf-8'))
            except Exception: pass

        # Guardar en Supabase DESPUÉS de cerrar stream (no bloquea al usuario)
        try:
            guardar_conversacion(session_id, messages, ip_hash, user_agent, respuesta_acumulada)
        except Exception as e:
            print(f"save error: {e}")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({
            "ok": True,
            "model": MODEL,
            "has_api_key": bool(MIMO_API_KEY),
            "has_supabase": bool(SUPABASE_URL and SUPABASE_KEY),
            "system_prompt_loaded": bool(get_system_prompt()),
        }).encode('utf-8'))

    def _send_error(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode('utf-8'))
