"""Parser inteligente: convierte mensajes de texto y fotos de tickets
en movimientos estructurados usando OpenAI."""
import base64
import datetime
import json
from typing import Optional

from openai import OpenAI
import pytz

import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)

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
la hucha", "uso la hucha", "gasto la hucha", "he usado la hucha", "tiro de la hucha", \
"quito de la hucha") -> OBLIGATORIO tipo="INGRESO" y categoria="Retirada de hucha". \
El campo hucha debe ser el nombre EXACTO de la lista de huchas validas que mas se \
parezca al mencionado (p.ej. "vacaciones"->"Vacaciones", "emergencia"->"Fondo de \
emergencia", "coche"->"Coche"). \
EJEMPLO: "retiro 200 de la hucha de vacaciones" -> {"tipo":"INGRESO", \
"categoria":"Retirada de hucha","hucha":"Vacaciones","importe":200}. \
Esta regla tiene PRIORIDAD sobre la regla 7 (no es un ingreso normal).
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
        huchas=", ".join(config.HUCHAS),
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
