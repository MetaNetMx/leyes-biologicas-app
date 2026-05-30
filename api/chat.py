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
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2000"))
# Mantener historial acotado para no exceder ventana de contexto
MAX_HISTORY_PAIRS = int(os.environ.get("MAX_HISTORY_PAIRS", "8"))

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


def trim_history(messages, max_pairs):
    """Conserva el primer mensaje (síntoma inicial) + últimos max_pairs turnos."""
    if len(messages) <= max_pairs * 2 + 1:
        return messages
    head = messages[:1] if messages and messages[0].get("role") == "user" else []
    tail = messages[-(max_pairs * 2):]
    # Asegurar que arranca con user
    if tail and tail[0].get("role") == "assistant":
        tail = tail[1:]
    return head + tail


def guardar_conversacion(session_id, mensajes, ip_hash, user_agent, respuesta_final):
    if not (SUPABASE_URL and SUPABASE_KEY and session_id):
        return

    sintoma_inicial = ""
    for m in mensajes:
        if m.get("role") == "user":
            sintoma_inicial = m.get("content", "")[:500]
            break

    genero_meditacion = False
    analisis = None
    try:
        if respuesta_final:
            r_low = respuesta_final.lower()
            if "meditacion" in r_low or "meditación" in r_low or '"meditacion"' in r_low:
                genero_meditacion = True
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

    try:
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

    def _emit(self, obj):
        try:
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode('utf-8'))
            try: self.wfile.flush()
            except Exception: pass
        except Exception:
            pass

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

        # Recortar historial para evitar context overflow
        messages_trimmed = trim_history(messages, MAX_HISTORY_PAIRS)

        payload = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": get_system_prompt(),
            "messages": messages_trimmed,
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

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self._set_cors()
        self.end_headers()

        # Llamar a MiMo y consumir el stream. Devuelve (texto, stop_reason, error).
        def stream_mimo(msgs):
            payload_local = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": get_system_prompt(),
                "messages": msgs,
                "stream": True,
            }
            req_local = urllib.request.Request(
                MIMO_URL,
                data=json.dumps(payload_local).encode('utf-8'),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {MIMO_API_KEY}",
                },
                method="POST",
            )
            acc = ""
            sr = None
            err = None
            try:
                with urllib.request.urlopen(req_local, timeout=110) as resp:
                    for line_bytes in resp:
                        line = line_bytes.decode('utf-8', errors='replace').strip()
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        try:
                            ev = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        et = ev.get("type")
                        if et == "content_block_delta":
                            text = ev.get("delta", {}).get("text", "")
                            if text:
                                acc += text
                                self._emit({"chunk": text})
                        elif et == "message_delta":
                            sr2 = ev.get("delta", {}).get("stop_reason")
                            if sr2:
                                sr = sr2
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}"
            except Exception as e:
                err = str(e)
            return acc, sr, err

        respuesta_acumulada, stop_reason, upstream_error = stream_mimo(messages_trimmed)

        # Retry server-side si MiMo devolvió vacío con end_turn (caso conocido)
        if not respuesta_acumulada and not upstream_error and stop_reason in ("end_turn", None):
            nudge = list(messages_trimmed) + [
                {"role": "assistant", "content": "(pausa)"},
                {"role": "user", "content": "Continúa con tu respuesta, por favor."}
            ]
            r2, sr2, err2 = stream_mimo(nudge)
            if r2:
                respuesta_acumulada = r2
                stop_reason = sr2

        # Si tras el retry sigue vacío, emitir error honesto
        if not respuesta_acumulada:
            if upstream_error:
                self._emit({"error": f"MiMo error: {upstream_error}"})
            else:
                self._emit({
                    "error": (
                        f"El modelo no respondió (stop_reason={stop_reason}). "
                        "Intenta reformular tu mensaje o empezar una nueva sesión."
                    )
                })

        # Marcar fin de stream
        self._emit({"done": True})

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
            "max_tokens": MAX_TOKENS,
            "max_history_pairs": MAX_HISTORY_PAIRS,
        }).encode('utf-8'))

    def _send_error(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode('utf-8'))
