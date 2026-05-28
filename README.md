# Leyes Biológicas — Coach autónomo

Aplicación web que aplica el marco de las 5 Leyes Biológicas (Mark Pfister, Dr. Hamer) como un asistente conversacional autónomo. Usa el API de MiMo (Xiaomi) con formato compatible Anthropic.

## Estructura del proyecto

```
vercel-deploy/
├── api/
│   ├── chat.py              ← Serverless function (backend)
│   └── system_prompt.txt    ← El skill compilado (109 KB)
├── public/
│   └── index.html           ← Frontend (React via CDN)
├── vercel.json              ← Configuración de Vercel
└── README.md                ← Este archivo
```

## Variables de entorno requeridas en Vercel

| Variable | Valor | Obligatoria |
|---|---|---|
| `MIMO_API_KEY` | Tu key de platform.xiaomimimo.com | Sí |
| `MODEL` | `mimo-v2.5-pro` (default) | No |
| `RATE_LIMIT_PER_MIN` | `20` (default) | No |
| `MAX_TOKENS` | `8000` (default) | No |

## Modelos disponibles en MiMo

- `mimo-v2.5-pro` — flagship, mejor para razonamiento (recomendado)
- `mimo-v2.5` — balance precio/calidad
- `mimo-v2-pro` — versión anterior
- `mimo-v2-flash` — más rápido, más barato

## Endpoints

- `POST /api/chat` — chat principal (SSE streaming)
- `GET /api/health` — verifica que el servidor está vivo y la API key cargada

## Desarrollo local

```bash
# Instalar Vercel CLI (una vez)
npm install -g vercel

# En esta carpeta
vercel dev
```

Abre http://localhost:3000

## Aviso médico

Esta app es una herramienta de exploración personal. No es diagnóstico médico ni sustituto de atención profesional.


---
Deployed via Vercel.
