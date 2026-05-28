# Guía paso a paso: subir a GitHub y deployar en Vercel

Tiempo total estimado: 15-20 minutos. No requiere instalar git ni terminal.

---

## PARTE 1: Subir el proyecto a GitHub (vía web)

### Paso 1: Crear el repositorio

1. Ve a [github.com/new](https://github.com/new)
2. **Repository name**: `leyes-biologicas-app` (o el nombre que quieras)
3. **Description** (opcional): "Coach de Leyes Biológicas"
4. Marca **Private** (recomendado, porque incluyes material del curso)
5. NO marques "Add a README", "Add .gitignore" ni "Choose a license" (los archivos ya los tienes)
6. Click en **Create repository**

### Paso 2: Subir los archivos

1. En la página del repo vacío que acabas de crear, verás un botón: **"uploading an existing file"**. Click ahí.
2. Abre el explorador de Windows y navega a:
   `C:\Users\Administrator\Desktop\claude\ELB\Leyes Biologicas\vercel-deploy\`
3. Selecciona TODO el contenido de esa carpeta (Ctrl+A) y arrástralo a la zona de subida de GitHub.
   - Asegúrate de que se suben las subcarpetas `api/` y `public/` también, no solo los archivos sueltos.
4. En la parte de abajo, donde dice "Commit changes":
   - Mensaje: `initial commit`
   - Selecciona "Commit directly to the main branch"
5. Click en **Commit changes**

Espera unos segundos. Cuando termine, verás en el repo los archivos: `api/`, `public/`, `vercel.json`, `README.md`, etc.

---

## PARTE 2: Conectar Vercel con tu GitHub

### Paso 3: Importar el proyecto en Vercel

1. Ve a [vercel.com](https://vercel.com) y entra con tu cuenta (la que ya tienes conectada).
2. En el dashboard, click en **Add New...** → **Project**.
3. Si es la primera vez, Vercel pedirá conectar tu cuenta de GitHub. Autoriza.
4. En la lista de repos verás `leyes-biologicas-app`. Click en **Import**.

### Paso 4: Configurar el deploy

En la pantalla de configuración:

1. **Framework Preset**: déjalo en **Other** (Vercel detectará la config del `vercel.json`).
2. **Root Directory**: déjalo en blanco o `./`.
3. NO toques los Build Settings (los lee del `vercel.json` automáticamente).
4. Despliega la sección **Environment Variables**. Aquí va lo importante:
   - **Key**: `MIMO_API_KEY`
   - **Value**: pega tu key de MiMo (la que sacaste de platform.xiaomimimo.com/console/api-keys)
   - Click en **Add**
5. (Opcional) Agrega también:
   - `MODEL` = `mimo-v2.5-pro`
   - `RATE_LIMIT_PER_MIN` = `20`
6. Click en **Deploy**.

Espera 2-3 minutos. Vercel hace el build, instala dependencias Python, y publica.

### Paso 5: Probarlo

Cuando termine, te muestra una pantalla de "Congratulations" con un preview. Hay un botón **Visit** o **Continue to Dashboard**.

Tu URL será algo como:
```
https://leyes-biologicas-app-tuusuario.vercel.app
```

Abre esa URL. Deberías ver el disclaimer. Acepta, y prueba escribiendo un síntoma (ej: "me duele la rodilla derecha"). Si todo está bien configurado, el coach te responde con preguntas adaptadas al síntoma.

### Verificar que la API key se cargó bien

Abre en el navegador:
```
https://tu-url.vercel.app/api/health
```

Debes ver algo como:
```json
{"ok": true, "model": "mimo-v2.5-pro", "has_api_key": true, "system_prompt_loaded": true}
```

Si `has_api_key` es `false`, la variable no se guardó. Vuelve al dashboard de Vercel → Settings → Environment Variables y verifica.

---

## PARTE 3: Solucionar problemas comunes

### Error: "MIMO_API_KEY no configurada en el servidor"

La variable de entorno no se guardó. En Vercel: **Project → Settings → Environment Variables**. Agrégala. Después tienes que **redeployar**: ve a **Deployments → ...** (los tres puntos del último deploy) → **Redeploy**.

### Error: "MiMo 401"

Tu API key de MiMo es inválida o expiró. Ve a platform.xiaomimimo.com, genera una nueva, actualiza en Vercel.

### Error: "MiMo 429"

Excediste el rate limit de tu plan en MiMo. Espera unos minutos o sube de plan.

### El chat no responde / queda pensando

Posibles causas:
- Timeout de Vercel (las funciones gratis tienen límite de 10 segundos, las pagadas hasta 5 minutos). El plan gratis es justo para conversaciones cortas. Si tu uso es alto, considera plan Pro.
- Error de red. Abre la consola del navegador (F12 → Console) y mira si hay errores rojos.

### Las respuestas no son JSON válido

El modelo `mimo-v2.5-pro` debería respetar el formato. Si responde texto libre, revisa que `system_prompt.txt` se haya subido correctamente al repo (es el archivo grande, ~110 KB).

---

## PARTE 4: Conectar tu propio dominio (opcional)

Si quieres usar `leyesbiologicas.tudominio.com` en lugar de la URL `*.vercel.app`:

1. En Vercel: **Project → Settings → Domains**
2. Escribe tu dominio y click **Add**
3. Vercel te da uno o dos registros DNS (CNAME o A) para configurar en tu proveedor de dominio
4. Espera 5-30 minutos para que propague
5. Vercel configura HTTPS automáticamente

---

## PARTE 5: Actualizar el código después

Si modificas algo en local y quieres publicarlo:

1. En tu repo de GitHub, navega al archivo a modificar
2. Click el lápiz (Edit this file)
3. Haz los cambios y commit
4. Vercel detecta el push y redespliega automáticamente en 1-2 minutos

Si vas a modificar varios archivos, mejor usa GitHub Desktop (app gráfica que descargas de [desktop.github.com](https://desktop.github.com)) para sincronizar la carpeta local con el repo.

---

## Costos esperados

### Plan gratuito (suficiente para empezar)
- Vercel: gratis (hasta 100 GB de bandwidth/mes)
- MiMo: según tu plan en xiaomimimo.com

### Con tráfico real (cientos de usuarios)
- Vercel Pro: $20/mes (te quita el límite de 10 segundos por función)
- MiMo: variable según uso

---

## Checklist final

- [ ] Repo creado en GitHub con todos los archivos
- [ ] Vercel conectado al repo
- [ ] Variable `MIMO_API_KEY` configurada en Vercel
- [ ] Deploy completado
- [ ] `/api/health` responde con `has_api_key: true`
- [ ] Probaste el chat con un síntoma y respondió coherente
- [ ] (Opcional) Dominio propio conectado

Cuando todo esté en verde, tu app está viva en internet y cualquiera con el link puede usarla sin instalar nada ni meter API keys.
