"""Parser inteligente: convierte mensajes de texto y fotos de tickets
en movimientos estructurados usando OpenAI."""
import base64
import datetime
import json
import time
from typing import Optional

from openai import OpenAI
import pytz

import config
import sheets

_client = OpenAI(api_key=config.OPENAI_API_KEY)

# Cache de nombres de huchas (se leen en vivo de la hoja, con TTL corto)
_huchas_cache = {"names": list(config.HUCHAS), "ts": 0.0}
_HUCHAS_TTL = 60  # segundos


def _get_hucha_names() -> list[str]:
    """Nombres de huchas en vivo (cacheados ~60s). Fallback a config.HUCHAS."""
    now = time.time()
    if now - _huchas_cache["ts"] > _HUCHAS_TTL:
        try:
            _huchas_cache["names"] = sheets.list_hucha_names()
        except Exception:
            _huchas_cache["names"] = list(config.HUCHAS)
        _huchas_cache["ts"] = now
    return _huchas_cache["names"]

SYSTEM_PROMPT = """Eres un parser de movimientos financieros personales en espanol. \
Tu unica tarea es convertir mensajes en lenguaje natural a un JSON estructurado.

CATEGORIAS DE INGRESO VALIDAS (debes elegir una exacta):
{cat_ingresos}

CATEGORIAS DE GASTO VALIDAS (debes elegir una exacta):
{cat_gastos}

METODOS DE PAGO VALIDOS:
{metodos}

HUCHAS VALIDAS (para aportaciones Y retiradas de hucha):
{huchas}

TIPOS DE ACTIVO VALIDOS (solo si es_inversion):
{tipos_activo}

REGLAS:
1. Devuelve SIEMPRE un unico objeto JSON, sin texto adicional, sin markdown.
2. Campos obligatorios: fecha (YYYY-MM-DD), tipo ("INGRESO" o "GASTO"), categoria, \
importe (numero positivo), metodo_pago, descripcion (corta), confianza (0.0 a 1.0).
3. Campos opcionales: subcategoria, hucha, notas.
3b. Si el mensaje describe una COMPRA de un activo financiero (ETF, fondo indexado, \
accion, cripto, bono) con cantidad (participaciones/acciones/unidades) Y precio \
unitario (o importe total), marca "es_inversion": true y anade: \
"activo" (nombre corto, p.ej. "IWDA" o "MSCI World"), "tipo_activo" (uno de la lista), \
"ticker" (ticker o ISIN si aparece), "cantidad" (numero de participaciones, float), \
"precio" (precio unitario, float), "broker" (si se menciona: investor, myinvestor, \
degiro, trade republic, ibkr, etc.). En ese caso: tipo="GASTO", \
categoria="Inversion aportada", importe = cantidad * precio, descripcion = activo. \
Palabras clave: "compra", "compre", "he comprado", "aporte a", "invertido en", \
"DCA", "mensual de...". Si solo se menciona "invertir X euros" SIN cantidad de \
participaciones, NO es es_inversion: es un gasto normal de categoria "Inversion aportada".
4. La fecha debe ser la de hoy si no se especifica. "ayer" = hoy-1. "el viernes" = \
viernes mas reciente pasado.
5. Si el usuario dice "ahorro para vacaciones" o similar -> categoria "Ahorro aportado" \
y hucha "Vacaciones".
5b. RETIRO DE HUCHA (PRIORITARIO): si el mensaje menciona sacar, retirar, usar o \
gastar dinero DE una hucha (palabras clave: "retiro", "retiro de la hucha", "saco de \
la hucha", "saque de la hucha", "uso la hucha", "gasto la hucha", "he usado la hucha", \
"tiro de la hucha", "quito de la hucha") -> OBLIGATORIO tipo="GASTO" y \
categoria="Retirada de hucha", con importe POSITIVO (el sistema lo convierte a \
negativo despues). El campo hucha debe ser el nombre EXACTO de la lista de huchas \
validas que mas se parezca al mencionado (p.ej. "vacaciones"->"Vacaciones", \
"emergencia"/"fondo de emergencia"->"Fondo de emergencia", "coche"->"Coche", \
"navidad"->"Navidad", "formacion"->"Formacion"). \
EJEMPLO: "saque 120 de la hucha de vacaciones" -> tipo=GASTO, \
categoria=Retirada de hucha, hucha=Vacaciones, importe=120. \
Esta regla tiene PRIORIDAD: NUNCA marques una retirada de hucha como INGRESO.
6. Si el usuario dice "invertir" o "aportar a la cartera" -> categoria "Inversion aportada".
7. Si el texto menciona "cobro", "nomina", "sueldo", "me han pagado" -> tipo INGRESO.
8. Cualquier palabra de compra o pago -> tipo GASTO.
9. Si el metodo de pago no se especifica, usa "Tarjeta debito" por defecto.
10. Confianza: 1.0 = total certeza, <0.8 = dudas (faltan datos, ambiguedad). \
Si faltan datos criticos (importe o categoria), confianza <= 0.5.
11. La descripcion debe ser breve (p.ej. "Mercadona", "Cena con amigos").
12. NO inventes importes ni categorias. Si el texto es ambiguo, baja la confianza.
"""


def _build_system_prompt() -> str:
    return SYSTEM_PROMPT.format(
        cat_ingresos="\n".join(f"- {c}" for c in config.CAT_INGRESOS),
        cat_gastos="\n".join(f"- {c}" for c in config.CAT_GASTOS),
        metodos=", ".join(config.METODOS_PAGO),
        huchas=", ".join(_get_hucha_names()),
        tipos_activo=", ".join(config.TIPOS_ACTIVO),
    )


def _today_context() -> str:
    tz = pytz.timezone(config.TIMEZONE)
    now = datetime.datetime.now(tz)
    dias = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    return (
        f"Hoy es {dias[now.weekday()]} {now.strftime('%d/%m/%Y')}. "
        f"Devuelve fecha en formato YYYY-MM-DD."
    )


def parse_text(mensaje: str) -> dict:
    """Parsea un mensaje de texto. Devuelve dict con datos + 'confianza'."""
    response = _client.chat.completions.create(
        model=config.MODEL_TEXT,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "system", "content": _today_context()},
            {"role": "user", "content": mensaje},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw = response.choices[0].message.content
    return _normalize(json.loads(raw))


def parse_ticket_image(image_bytes: bytes) -> dict:
    """Parsea una foto de ticket. Devuelve el mismo tipo de dict."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt_user = (
        "Esta es la foto de un ticket de compra. Extrae: fecha del ticket "
        "(si no se ve, usa hoy), importe TOTAL pagado, nombre del comercio "
        "(para descripcion) y deduce la categoria. Si es un supermercado "
        "conocido -> Alimentacion/Supermercado. Si es un bar/restaurante -> "
        "Restaurantes/Bares. Si es una farmacia -> Salud/Farmacia. Etc. "
        "Si el importe no se lee claramente, confianza <= 0.4."
    )
    response = _client.chat.completions.create(
        model=config.MODEL_VISION,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "system", "content": _today_context()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_user},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=500,
    )
    raw = response.choices[0].message.content
    return _normalize(json.loads(raw))


def _normalize(data: dict) -> dict:
    """Normaliza y valida el diccionario devuelto por el modelo."""
    # Fecha a objeto date
    fecha_str = data.get("fecha", "")
    try:
        data["fecha"] = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        tz = pytz.timezone(config.TIMEZONE)
        data["fecha"] = datetime.datetime.now(tz).date()

    # Tipo en mayusculas
    data["tipo"] = str(data.get("tipo", "GASTO")).upper()
    if data["tipo"] not in ("INGRESO", "GASTO"):
        data["tipo"] = "GASTO"

    # Importe absoluto
    try:
        data["importe"] = abs(float(data.get("importe", 0)))
    except (ValueError, TypeError):
        data["importe"] = 0.0

    # Confianza por defecto
    try:
        data["confianza"] = float(data.get("confianza", 0.5))
    except (ValueError, TypeError):
        data["confianza"] = 0.5

    # Metodo pago por defecto
    if not data.get("metodo_pago"):
        data["metodo_pago"] = "Tarjeta debito"

    # Estado por defecto
    data["estado"] = "REAL"

    # Asegurar strings en campos opcionales
    for k in ("subcategoria", "descripcion", "hucha", "notas", "categoria"):
        data[k] = str(data.get(k, "")).strip()

    # Campos de inversion
    data["es_inversion"] = bool(data.get("es_inversion"))
    if data["es_inversion"]:
        for k in ("activo", "tipo_activo", "ticker", "broker"):
            data[k] = str(data.get(k, "")).strip()
        try:
            data["cantidad"] = float(data.get("cantidad", 0) or 0)
        except (ValueError, TypeError):
            data["cantidad"] = 0.0
        try:
            data["precio"] = float(data.get("precio", 0) or 0)
        except (ValueError, TypeError):
            data["precio"] = 0.0
        # Si faltan datos basicos, degradar: no es inversion estructurada
        if data["cantidad"] <= 0 or data["precio"] <= 0 or not data["activo"]:
            data["es_inversion"] = False
        else:
            # Recalcular importe total desde cantidad*precio
            data["importe"] = round(data["cantidad"] * data["precio"], 2)
            data["tipo"] = "GASTO"
            data["categoria"] = "Inversion aportada"
            if not data["descripcion"]:
                data["descripcion"] = data["activo"]

    return data


def _parse_iso_date(s) -> Optional[datetime.date]:
    """Parsea 'YYYY-MM-DD' (o dd/mm/yyyy) a date, o None."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _num_robusto(v) -> float:
    """Convierte numero o string (con € , .) a float. 0.0 si no se puede."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("€", "").replace(" ", "").strip()
    if not s:
        return 0.0
    try:
        return float(s)                       # "118.2673992", "200"
    except ValueError:
        try:
            return float(s.replace(".", "").replace(",", "."))  # "1.234,56"
        except ValueError:
            return 0.0


def _normalize_investment_image(data: dict) -> dict:
    """Normaliza la respuesta de una imagen de inversion en una lista de compras
    listas para append_investment. precio = importe / participaciones (exacto)."""
    tz = pytz.timezone(config.TIMEZONE)
    hoy = datetime.datetime.now(tz).date()
    fecha_global = _parse_iso_date(data.get("fecha")) or hoy

    compras = []
    for c in (data.get("compras") or []):
        activo = str(c.get("activo", "")).strip()
        importe = abs(_num_robusto(c.get("importe", 0)))
        participaciones = abs(_num_robusto(c.get("participaciones", 0)))
        if not activo or importe <= 0 or participaciones <= 0:
            continue
        precio = importe / participaciones  # NAV por participacion (informativo)
        compras.append({
            "es_inversion": True,
            "activo": activo,
            "tipo_activo": str(c.get("tipo_activo", "") or "Fondo indexado"),
            "ticker": str(c.get("ticker", "") or ""),
            "cantidad": participaciones,
            "precio": precio,
            "importe": round(importe, 2),
            "broker": str(c.get("broker", "") or ""),
            "fecha": _parse_iso_date(c.get("fecha")) or fecha_global,
            "tipo": "GASTO",
            "categoria": "Inversion aportada",
            "descripcion": activo,
            "metodo_pago": "Transferencia",
            "estado": "REAL",
            "notas": "",
            "confianza": 0.9,
        })
    return {"clasif": "inversion", "compras": compras}


def parse_photo(image_bytes: bytes) -> dict:
    """Analiza una foto. Distingue entre:
      - confirmacion de compra(s) de inversion -> {'clasif':'inversion','compras':[...]}
      - ticket de gasto normal               -> dict de movimiento + 'clasif'='gasto'
    """
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt_user = (
        "Analiza la imagen. Puede ser UNA de estas dos cosas:\n"
        "1) CONFIRMACION DE INVERSION: compra/suscripcion de fondos, ETFs, acciones "
        "o cripto, posiblemente con VARIAS operaciones en la misma captura (apps tipo "
        "MyInvestor, etc.). En ese caso devuelve EXACTAMENTE este JSON: "
        '{"clasif":"inversion","fecha":"YYYY-MM-DD","compras":['
        '{"activo":"nombre del activo tal cual aparece","importe":NUMERO_EUR,'
        '"participaciones":NUMERO,"broker":"si se ve"}]}. '
        "El importe es el dinero invertido en euros; participaciones es el numero de "
        "participaciones/acciones adquiridas (puede tener muchos decimales). Si la fecha "
        "aparece una sola vez (arriba), aplicala a todas las compras. Incluye TODAS las "
        "operaciones que veas.\n"
        "2) TICKET DE GASTO normal (compra en tienda/super/bar): devuelve este JSON: "
        '{"clasif":"gasto","tipo":"GASTO","importe":TOTAL,"categoria":"...",'
        '"descripcion":"comercio","metodo_pago":"...","fecha":"YYYY-MM-DD","confianza":0.0-1.0}. '
        "Elige la categoria de la lista de categorias de gasto validas.\n"
        "Devuelve SOLO el JSON, sin texto adicional."
    )
    response = _client.chat.completions.create(
        model=config.MODEL_VISION,
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "system", "content": _today_context()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_user},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=900,
    )
    data = json.loads(response.choices[0].message.content)
    if str(data.get("clasif", "")).lower() == "inversion":
        return _normalize_investment_image(data)
    norm = _normalize(data)
    norm["clasif"] = "gasto"
    return norm
