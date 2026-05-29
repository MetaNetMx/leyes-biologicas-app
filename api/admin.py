"""
Endpoint admin protegido por token.
GET /api/admin?token=XXX → dashboard HTML con stats
GET /api/admin?token=XXX&format=json → JSON crudo
GET /api/admin?token=XXX&action=detalle&id=YYY → conversación completa
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
from html import escape

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def supabase_get(path):
    if not (SUPABASE_URL and SUPABASE_KEY):
        return None
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def calcular_stats():
    """Trae todas las conversaciones y calcula stats."""
    convs = supabase_get("lb_conversaciones?select=*&order=created_at.desc&limit=500") or []

    total = len(convs)
    con_meditacion = sum(1 for c in convs if c.get('genero_meditacion'))
    sintomas = []
    tejidos_freq = {}
    hojas_freq = {}
    matices_freq = {}

    for c in convs:
        if c.get('sintoma_inicial'):
            sintomas.append({
                "id": c['id'],
                "fecha": c['created_at'],
                "sintoma": c['sintoma_inicial'][:200],
                "num_msg": c.get('num_mensajes', 0),
                "meditacion": c.get('genero_meditacion'),
            })
        anal = c.get('analisis')
        if anal and isinstance(anal, dict):
            tejidos = anal.get('tejidos', []) or []
            for t in tejidos:
                if isinstance(t, dict):
                    n = t.get('nombre', '')
                    if n: tejidos_freq[n] = tejidos_freq.get(n, 0) + 1
                    h = t.get('hoja_embrionaria', '')
                    if h: hojas_freq[h] = hojas_freq.get(h, 0) + 1
                    m = t.get('matiz_emocional', '')
                    if m: matices_freq[m[:100]] = matices_freq.get(m[:100], 0) + 1

    return {
        "total_conversaciones": total,
        "con_meditacion": con_meditacion,
        "pct_meditacion": round(100 * con_meditacion / total, 1) if total else 0,
        "tejidos_top": sorted(tejidos_freq.items(), key=lambda x: -x[1])[:15],
        "hojas_top": sorted(hojas_freq.items(), key=lambda x: -x[1]),
        "matices_top": sorted(matices_freq.items(), key=lambda x: -x[1])[:10],
        "conversaciones": sintomas,
    }


def render_html(stats):
    tejidos_html = "".join(f"<tr><td>{escape(t)}</td><td>{n}</td></tr>" for t, n in stats['tejidos_top'])
    hojas_html = "".join(f"<tr><td>{escape(h)}</td><td>{n}</td></tr>" for h, n in stats['hojas_top'])
    matices_html = "".join(f"<tr><td>{escape(m)}</td><td>{n}</td></tr>" for m, n in stats['matices_top'])

    convs_html = ""
    for c in stats['conversaciones']:
        med = "🧘" if c['meditacion'] else ""
        fecha = c['fecha'][:16].replace("T", " ")
        convs_html += f"""
        <tr>
          <td style="font-size:11px;color:#666">{escape(fecha)}</td>
          <td>{escape(c['sintoma'])}</td>
          <td style="text-align:center">{c['num_msg']}</td>
          <td style="text-align:center">{med}</td>
          <td><a href="?token={escape(ADMIN_TOKEN)}&action=detalle&id={escape(c['id'])}" target="_blank">ver</a></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Admin · Leyes Biológicas</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; background: #faf7f2; padding: 20px; max-width: 1200px; margin: auto; color: #1a3a52; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 16px; margin-top: 30px; color: #5c7c8c; }}
  .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 30px; }}
  .stat {{ background: white; padding: 16px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
  .stat .num {{ font-size: 28px; font-weight: 600; color: #c47b5a; }}
  .stat .lbl {{ font-size: 12px; color: #666; text-transform: uppercase; }}
  table {{ width: 100%; background: white; border-radius: 8px; border-collapse: collapse; margin-bottom: 24px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.04); }}
  th {{ background: #1a3a52; color: white; padding: 10px; text-align: left; font-weight: 500; font-size: 12px; text-transform: uppercase; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #f0ebe1; font-size: 13px; }}
  tr:hover td {{ background: #fafafa; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  a {{ color: #c47b5a; }}
</style>
</head><body>
<h1>Dashboard Leyes Biológicas</h1>
<div class="stats">
  <div class="stat"><div class="num">{stats['total_conversaciones']}</div><div class="lbl">Conversaciones</div></div>
  <div class="stat"><div class="num">{stats['con_meditacion']}</div><div class="lbl">Con meditación</div></div>
  <div class="stat"><div class="num">{stats['pct_meditacion']}%</div><div class="lbl">% solicitaron meditación</div></div>
</div>

<div class="grid2">
  <div>
    <h2>Tejidos más identificados</h2>
    <table><tr><th>Tejido</th><th>Veces</th></tr>{tejidos_html}</table>
  </div>
  <div>
    <h2>Hojas embrionarias</h2>
    <table><tr><th>Hoja</th><th>Veces</th></tr>{hojas_html}</table>
  </div>
</div>

<h2>Matices emocionales recurrentes</h2>
<table><tr><th>Matiz</th><th>Veces</th></tr>{matices_html}</table>

<h2>Últimas conversaciones</h2>
<table>
  <tr><th>Fecha</th><th>Síntoma inicial</th><th>#msgs</th><th>Med</th><th></th></tr>
  {convs_html}
</table>
</body></html>"""


def render_detalle_html(conv):
    msgs_html = ""
    for m in conv.get('mensajes', []):
        rol = m.get('role', '')
        cnt = m.get('content', '')
        color = "#1a3a52" if rol == "assistant" else "#c47b5a"
        msgs_html += f"""
        <div style="margin-bottom:16px;border-left:3px solid {color};padding:8px 12px;background:white;border-radius:6px">
          <div style="font-size:11px;color:#888;text-transform:uppercase;margin-bottom:6px">{escape(rol)}</div>
          <div style="white-space:pre-wrap">{escape(cnt)}</div>
        </div>"""

    analisis_html = ""
    if conv.get('analisis'):
        analisis_html = f"<pre style='background:#fff8e1;padding:12px;border-radius:6px;overflow-x:auto'>{escape(json.dumps(conv['analisis'], indent=2, ensure_ascii=False))}</pre>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Detalle</title>
<style>body{{font-family:-apple-system,sans-serif;background:#faf7f2;padding:20px;max-width:900px;margin:auto;color:#1a3a52}}</style>
</head><body>
<a href="javascript:history.back()">← volver</a>
<h2>Conversación {escape(conv['id'][:8])}</h2>
<p style="color:#666">Fecha: {escape(conv['created_at'][:16].replace('T', ' '))} · Mensajes: {conv.get('num_mensajes', 0)} · Meditación: {'sí' if conv.get('genero_meditacion') else 'no'}</p>
<h3>Análisis identificado</h3>
{analisis_html or '<p>(sin análisis estructurado)</p>'}
<h3>Mensajes</h3>
{msgs_html}
</body></html>"""


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        # Parsear query
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        token = (qs.get('token') or [''])[0]
        action = (qs.get('action') or [''])[0]
        formato = (qs.get('format') or ['html'])[0]
        conv_id = (qs.get('id') or [''])[0]

        if not ADMIN_TOKEN or token != ADMIN_TOKEN:
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Unauthorized. Add ?token=YOUR_TOKEN")
            return

        try:
            if action == 'detalle' and conv_id:
                rows = supabase_get(f"lb_conversaciones?id=eq.{conv_id}")
                if not rows:
                    self.send_response(404)
                    self.end_headers()
                    return
                html = render_detalle_html(rows[0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
                return

            stats = calcular_stats()

            if formato == 'json':
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(stats, ensure_ascii=False, default=str).encode('utf-8'))
                return

            html = render_html(stats)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Error: {str(e)}".encode('utf-8'))
