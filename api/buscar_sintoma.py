"""
Endpoint /api/buscar_sintoma
Recibe un síntoma en texto libre, busca en el cofre de los achaques (575 síntomas),
y devuelve los 5 más cercanos enriquecidos con LLM (Claude vía MiMo) con la
estructura completa: órgano, hoja embrionaria, fase, matiz emocional, conflicto.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import time
import re
import urllib.request
import urllib.error
from pathlib import Path
from collections import defaultdict, deque

MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MODEL = os.environ.get("MODEL", "mimo-v2.5-pro")
MIMO_URL = "https://api.xiaomimimo.com/anthropic/v1/messages"

RATE_LIMIT = int(os.environ.get("BUSCAR_RATE_PER_MIN", "20"))
_buckets = defaultdict(lambda: deque(maxlen=RATE_LIMIT))


def check_rate(ip):
    now = time.time()
    b = _buckets[ip]
    while b and b[0] < now - 60:
        b.popleft()
    if len(b) >= RATE_LIMIT:
        return False
    b.append(now)
    return True


# Cache del cofre cargado en cold start
_COFRE = None

def get_cofre():
    global _COFRE
    if _COFRE is None:
        for path in [
            Path(__file__).parent.parent / "public" / "data" / "cofre.json",
            Path("/var/task/public/data/cofre.json"),
            Path(__file__).parent / "cofre.json",
        ]:
            if path.exists():
                _COFRE = json.loads(path.read_text(encoding='utf-8'))
                break
        if _COFRE is None:
            _COFRE = {"cofres": {}, "total": 0}
    return _COFRE


# Stopwords español para mejor matching
STOP = set("a al algo algun alguna algunas alguno algunos ambos ampleamos ante antes aquel aquellas aquellos aqui arriba atras bajo bastante bien cada ciertas ciertos como con conseguimos conseguir consigo consigue consiguen consigues cual cuando dentro desde donde dos el ellas ellos empleais emplean emplear empleas empleo en encima entonces entre era eramos eran eras eres es esa esas ese eso esos esta estaba estado estais estamos estan estoy fin fue fueron fui fuimos ha hace haceis hacemos hacen hacer haces hago incluso intenta intentais intentamos intentan intentar intentas intento ir la largo las lo los me mi mio modo muchos muy nos nosotros otro para pero podeis podemos poder podria podriais podriamos podrian podrias por por que porque primero puede pueden puedo quien sabe sabeis sabemos saben saber sabes ser si siendo sin sobre sois solamente solo somos soy su sus tambien teneis tenemos tener tengo tiempo tiene tienen todo trabaja trabajais trabajamos trabajan trabajar trabajas trabajo tras tuyo ultimo un una unas uno unos usa usais usamos usan usar usas uso va vais valor vamos van vaya verdad verdadera verdadero vosotras vosotros voy yo".split())


def tokenize(text):
    if not text: return set()
    text = text.lower()
    text = re.sub(r'[^a-záéíóúñü\s]', ' ', text)
    tokens = [t for t in text.split() if t and t not in STOP and len(t) > 2]
    return set(tokens)


def score_match(query_tokens, sintoma):
    """Score de coincidencia entre query y un síntoma del cofre."""
    desc = sintoma.get('descripcion', '') or ''
    organo = sintoma.get('organo', '') or ''
    text = (desc + ' ' + organo).lower()
    s_tokens = tokenize(text)
    if not query_tokens or not s_tokens:
        return 0
    # Jaccard-style con boost por inclusión literal
    matches = query_tokens & s_tokens
    score = len(matches) / max(len(query_tokens), 1)
    # Boost si query como substring está en desc
    if len(query_tokens) > 0:
        joined = ' '.join(query_tokens)
        if joined and joined in text:
            score += 0.5
    return score


def buscar_en_cofre(query, top_k=8):
    cofre = get_cofre()
    q_tokens = tokenize(query)
    resultados = []
    for slug, data in cofre.get('cofres', {}).items():
        for s in data.get('sintomas', []):
            score = score_match(q_tokens, s)
            if score > 0:
                resultados.append({
                    'score': round(score, 3),
                    'cofre_slug': slug,
                    'num': s.get('num'),
                    'descripcion': s.get('descripcion'),
                    'organo': s.get('organo'),
                    'capa': s.get('capa'),
                    'fase': s.get('fase'),
                })
    resultados.sort(key=lambda x: -x['score'])
    return resultados[:top_k]


def enriquecer_con_llm(query, matches):
    """Pide a Claude que dé una respuesta sintetizada con todas las características."""
    if not MIMO_API_KEY:
        return None

    contexto = "\n".join([
        f"- {m['descripcion']} | Órgano: {m.get('organo','?')} | Capa: {m.get('capa','?')} | Fase: {m.get('fase','?')} [cofre: {m['cofre_slug']}, #{m['num']}]"
        for m in matches
    ])

    sistema = (
        "Eres un experto en las Leyes Biológicas de Hamer (marco de Mark Pfister). "
        "Te paso una consulta del usuario y los síntomas más cercanos del Cofre de los Achaques del curso. "
        "Responde en español, directo, sin frases de relleno. Estructura tu respuesta así:\n"
        "\n1. **Lectura biológica del síntoma**: explica qué órgano(s) probable(s) están implicados, capa embrionaria, fase del SBS.\n"
        "2. **Matiz emocional / conflicto biológico**: el contenido emocional (DHS) que típicamente está detrás.\n"
        "3. **Sentido biológico**: para qué le sirve al organismo este programa biológico.\n"
        "4. **Comportamiento del tejido**: qué ocurre en fase activa vs PCL.\n"
        "5. **Lateralidad / detalles relevantes** (si aplica).\n"
        "6. **Sugerencias** (sin diagnosticar): preguntas para indagar el DHS, qué observar.\n\n"
        "No inventes información. Si los matches del cofre no son cercanos al síntoma consultado, dilo claro. "
        "Cierra recordando que no es diagnóstico médico."
    )

    user_msg = (
        f"Consulta del usuario: \"{query}\"\n\n"
        f"Síntomas más cercanos del Cofre de los Achaques:\n{contexto}\n\n"
        f"Da la lectura biológica completa siguiendo el formato indicado."
    )

    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "system": sistema,
        "messages": [{"role": "user", "content": user_msg}],
    }

    req = urllib.request.Request(
        MIMO_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {MIMO_API_KEY}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=55) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = data.get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "")
    except Exception as e:
        return f"(No se pudo obtener lectura enriquecida: {e})"
    return None


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
        client_ip = self.headers.get('x-forwarded-for', 'unknown').split(',')[0].strip()
        if not check_rate(client_ip):
            self._err(429, "Demasiadas búsquedas. Intenta en un minuto.")
            return

        try:
            length = int(self.headers.get('content-length', 0))
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            query = (data.get('query') or '').strip()
            enriquecer = data.get('enriquecer', True)
            if not query or len(query) < 3:
                self._err(400, "Describe el síntoma con al menos 3 caracteres")
                return
        except (ValueError, json.JSONDecodeError) as e:
            self._err(400, f"Body inválido: {e}")
            return

        matches = buscar_en_cofre(query, top_k=8)
        lectura = None
        if enriquecer and matches:
            lectura = enriquecer_con_llm(query, matches[:5])

        resp = {
            "query": query,
            "matches": matches,
            "lectura": lectura,
            "total_en_cofre": get_cofre().get('total', 0),
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        # Health check del endpoint
        cofre = get_cofre()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({
            "endpoint": "/api/buscar_sintoma",
            "method": "POST",
            "body": {"query": "describe el síntoma", "enriquecer": True},
            "cofre_cargado": cofre.get('total', 0),
            "cofres": list(cofre.get('cofres', {}).keys()),
        }).encode('utf-8'))

    def _err(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode('utf-8'))
