# Bot de Finanzas Personales (Telegram + OpenAI + Google Sheets)

Bot de Telegram que convierte mensajes en lenguaje natural y fotos de tickets en
movimientos registrados automáticamente en tu Google Sheet de control financiero.

## Qué hace

- Entiende mensajes como *"35 en el merca"*, *"ayer 12 farmacia bizum"*, *"nómina 2400"*.
- Lee fotos de tickets (OCR con GPT-4o Vision) y extrae importe, comercio y categoría.
- Pide confirmación con botones inline antes de guardar.
- Escribe directamente en la pestaña `TRACKER` de tu Google Sheet.
- Registra **compras de inversión** (ETFs, fondos, acciones) en la hoja
  `INVERSIONES` (posición + historial) y simultáneamente en `TRACKER` como
  gasto `Inversion aportada`. Si la posición ya existe, recalcula el precio
  medio ponderado.
- Comandos: `/resumen`, `/huchas`, `/cartera`, `/categoria`, `/ultimos`, `/deshacer`.
- Solo responde a tu `chat_id` autorizado (el bot ignora a cualquier otro usuario).

## Archivos del proyecto

```
bot-finanzas/
├── bot.py              # Servidor principal (Telegram handlers)
├── parser.py           # Parser con OpenAI (texto y visión)
├── sheets.py           # Acceso a Google Sheets
├── config.py           # Carga de variables de entorno
├── requirements.txt    # Dependencias Python
├── Procfile            # Instrucción de arranque para Railway
├── runtime.txt         # Versión de Python
├── .env.example        # Plantilla de variables
└── README.md           # Este archivo
```

---

## Despliegue en Railway (paso a paso)

### Requisitos previos
- Cuenta de GitHub (gratis).
- Cuenta de Railway (gratis, se registra con GitHub).
- Ya debes tener obtenidas las credenciales:
  - Token del bot de Telegram (@BotFather)
  - Tu chat_id (@userinfobot)
  - API key de OpenAI
  - Archivo JSON de Service Account de Google Cloud
  - Tu Google Sheet compartido con el email del Service Account

---

### Paso 1 — Subir el código a GitHub

1. Ve a https://github.com/new y crea un repositorio **privado** llamado `bot-finanzas`.
2. En el ordenador, abre una terminal dentro de la carpeta `bot-finanzas/` y ejecuta:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/bot-finanzas.git
   git push -u origin main
   ```
   (Sustituye `TU_USUARIO` por tu usuario de GitHub).

   **Alternativa sin terminal:** en la página del repo recién creado, usa
   "uploading an existing file" y arrastra todos los archivos (menos `.env` si
   existe — el `.gitignore` ya lo excluye).

---

### Paso 2 — Crear el proyecto en Railway

1. Entra en https://railway.app y pulsa **"Start a New Project"**.
2. Elige **"Deploy from GitHub repo"**.
3. Autoriza Railway a acceder a tu GitHub si es la primera vez.
4. Selecciona el repo `bot-finanzas`.
5. Railway empezará a construir el proyecto automáticamente (tardará 2-3 minutos).

---

### Paso 3 — Configurar variables de entorno

En el panel del proyecto de Railway:

1. Clic en el servicio recién creado.
2. Pestaña **"Variables"**.
3. Pulsa **"+ New Variable"** para cada una de estas:

| Nombre | Valor |
|--------|-------|
| `TELEGRAM_BOT_TOKEN` | *(tu token de BotFather)* |
| `AUTHORIZED_CHAT_ID` | `6608672366` |
| `OPENAI_API_KEY` | *(tu API key de OpenAI)* |
| `GOOGLE_SHEET_ID` | `1SC-VwpYVAjbI7r-wYQ1VzBKyEgUQeM5ODjp5GmtzgU4` |
| `TRACKER_SHEET_NAME` | `TRACKER` |
| `GOOGLE_CREDENTIALS_JSON` | *(ver siguiente paso)* |
| `TIMEZONE` | `Europe/Madrid` |

---

### Paso 4 — Variable `GOOGLE_CREDENTIALS_JSON` (la más delicada)

Abre el archivo JSON que descargaste del Service Account. Su contenido es algo así:

```json
{
  "type": "service_account",
  "project_id": "control-financiero-...",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "bot-finanzas@....iam.gserviceaccount.com",
  ...
}
```

**Debes pegar TODO el contenido del archivo como valor de la variable
`GOOGLE_CREDENTIALS_JSON`** (Railway acepta valores multilínea, solo cópialo tal cual).

Importante: no modifiques el `private_key`. Debe conservar los `\n` literales.

---

### Paso 5 — Arrancar el worker

Por defecto Railway arranca un "web service" (espera puerto HTTP). Como nosotros
queremos un worker (bot de Telegram por polling), hay que cambiar el tipo:

1. En Railway, pestaña **"Settings"** del servicio.
2. Busca **"Start Command"** y escribe:
   ```
   python bot.py
   ```
3. Si hay una opción **"Service Type"** o **"Process Type"**, selecciona `worker`
   (si no existe, no pasa nada — con el Start Command arriba es suficiente).
4. Pulsa **"Deploy"** (o espera a que re-despliegue solo tras cambiar la variable).

---

### Paso 6 — Verificar que el bot está vivo

1. En Railway, pestaña **"Logs"** del servicio. Deberías ver algo como:
   ```
   [INFO] bot-finanzas: Configuracion validada. Iniciando bot...
   [INFO] bot-finanzas: Bot arrancado. Esperando mensajes...
   ```
2. Abre Telegram, busca tu bot (por el username que le diste a BotFather) y
   escríbele `/start`. Debería responderte con el mensaje de bienvenida.

3. Prueba con un mensaje real:
   ```
   35 en el merca con tarjeta
   ```
   El bot te responderá con los datos parseados y botones *Guardar / Cancelar*.
   Al pulsar Guardar, comprueba tu Google Sheet: debe aparecer la fila nueva.

---

## Desarrollo local (opcional, para probar antes de desplegar)

Si quieres probarlo en tu ordenador antes de subirlo a Railway:

1. Instala Python 3.12 desde https://www.python.org/downloads/.
2. En la carpeta del proyecto:
   ```bash
   python -m venv venv
   venv\Scripts\activate      # Windows
   # source venv/bin/activate  # Mac/Linux
   pip install -r requirements.txt
   ```
3. Copia `.env.example` a `.env` y rellena los valores.
4. Arranca el bot:
   ```bash
   python bot.py
   ```

---

## Costes estimados

| Servicio | Coste |
|----------|-------|
| Railway (500h/mes gratis) | 0 EUR |
| OpenAI (`gpt-4o-mini` texto) | ~0,0001 EUR por mensaje |
| OpenAI (`gpt-4o` ticket foto) | ~0,005 EUR por foto |
| Google Sheets API | Gratis |
| Telegram Bot API | Gratis |

**Uso estimado**: 200 gastos/mes + 20 fotos de ticket = unos **0,15 EUR/mes**.

---

## Comandos del bot

| Comando | Qué hace |
|---------|----------|
| `/start` | Mensaje de bienvenida |
| `/help` | Lista de comandos |
| `/resumen` | KPIs del mes actual (ingresos, gastos, balance, tasa ahorro) |
| `/huchas` | Progreso actual de las huchas |
| `/cartera` | Posiciones actuales de inversión (participaciones, precio medio, G/P) |
| `/categoria <nombre>` | Total gastado en esa categoría este mes. Ej: `/categoria aliment` |
| `/ultimos` | Últimos 10 movimientos registrados |
| `/deshacer` | Borra el último movimiento añadido por el bot |

Además:
- **Cualquier texto libre** se parsea como movimiento.
- **Cualquier foto** se interpreta como ticket de compra.

---

## Ejemplos de frases que entiende

| Escribes | Interpreta |
|----------|-----------|
| `35 en el merca` | GASTO 35€, Alimentación/Supermercado, Mercadona |
| `ayer 12 farmacia bizum` | GASTO 12€, fecha ayer, Salud/Farmacia, Bizum |
| `nómina 2400` | INGRESO 2400€, Nómina |
| `150 a la hucha de vacaciones` | GASTO Ahorro aportado, hucha Vacaciones |
| `he invertido 200 en el MSCI` | GASTO Inversión aportada, notas MSCI |
| `compra 5 IWDA a 82` | Inversión: nueva posición IWDA (5 part. @ 82€) + TRACKER |
| `he comprado 20 VWCE a 110€ con investor` | Inversión con broker MyInvestor |
| `aporte mensual 10 participaciones MSCI World a 95` | Actualiza posición y precio medio |
| `cena con amigos 38 euros con tarjeta de crédito` | GASTO 38€, Restaurantes, Tarjeta crédito |
| `repostaje coche 62` | GASTO 62€, Transporte (gasolina/parking) |

---

## Solución de problemas

**El bot no responde a mis mensajes.**
- Revisa los logs en Railway. Busca errores.
- Verifica que `AUTHORIZED_CHAT_ID` coincide exactamente con tu chat_id.

**"Error: APIError: The caller does not have permission" al guardar.**
- No compartiste el Google Sheet con el email del Service Account.
- Abre el Sheet → Compartir → pega el `client_email` del JSON → Editor.

**"GOOGLE_CREDENTIALS_JSON no es un JSON válido".**
- Al pegar la variable en Railway, algún carácter se rompió. Vuelve a pegar el
  JSON completo desde el archivo descargado.

**El parser confunde categorías.**
- Es normal al principio. Cuando algo se categoriza mal, pulsa "Cancelar" y
  reescribe el mensaje dando más contexto (p.ej. *"35 en supermercado Mercadona"*
  en vez de solo *"35 en el merca"*).

**Quiero que el bot ya no pida confirmación si su confianza es alta.**
- Edita `bot.py`, función `_send_confirmation`. Al principio añade:
  ```python
  if data["confianza"] >= 0.9 and not es_ticket:
      row = await asyncio.to_thread(sheets.append_movement, data)
      last_written_row[update.effective_chat.id] = row
      await update.message.reply_text(f"Guardado directo (confianza {int(data['confianza']*100)}%).")
      return
  ```

---

## Seguridad

- **Nunca subas el archivo `.env`** ni el JSON de Google Cloud a GitHub
  (el `.gitignore` ya los excluye).
- Las credenciales solo viven en las variables de entorno de Railway (cifradas).
- Si sospechas que alguna credencial se ha filtrado, **rótala inmediatamente**:
  - Telegram: `/revoke` con @BotFather.
  - OpenAI: dashboard > API keys > Revoke.
  - Google Cloud: IAM & Admin > Service Accounts > borra la key y genera otra.
