"""Configuración centralizada. Carga variables de entorno desde .env o Railway."""
import os
import json
from dotenv import load_dotenv

load_dotenv()

# ─── Credenciales ────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AUTHORIZED_CHAT_ID = int(os.getenv("AUTHORIZED_CHAT_ID", "0"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

# ─── Google Sheets ───────────────────────────────────────────────
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
TRACKER_SHEET_NAME = os.getenv("TRACKER_SHEET_NAME", "TRACKER").strip()
HUCHAS_SHEET_NAME = os.getenv("HUCHAS_SHEET_NAME", "HUCHAS").strip()
PRESUPUESTO_SHEET_NAME = os.getenv("PRESUPUESTO_SHEET_NAME", "PRESUPUESTO").strip()
INVERSIONES_SHEET_NAME = os.getenv("INVERSIONES_SHEET_NAME", "INVERSIONES").strip()

# Opcion A: ruta a un archivo JSON (recomendado en servidor propio)
_creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()
# Opcion B: el JSON entero en una variable de entorno (Railway, etc.)
_raw_creds = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()

GOOGLE_CREDENTIALS = None
if _creds_file:
    try:
        with open(_creds_file, "r", encoding="utf-8") as f:
            GOOGLE_CREDENTIALS = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"No se pudo leer GOOGLE_CREDENTIALS_FILE ({_creds_file}): {e}")
elif _raw_creds:
    try:
        GOOGLE_CREDENTIALS = json.loads(_raw_creds)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GOOGLE_CREDENTIALS_JSON no es un JSON valido: {e}")

# ─── Otros ───────────────────────────────────────────────────────
TIMEZONE = os.getenv("TIMEZONE", "Europe/Madrid")
MODEL_TEXT = os.getenv("MODEL_TEXT", "gpt-4o-mini")
# Separador de argumentos en formulas escritas via API.
# Hojas en español/europeo usan ';'; en_US/en_GB usan ','.
SHEETS_FORMULA_SEP = (os.getenv("SHEETS_FORMULA_SEP", ";").strip() or ";")
MODEL_VISION = os.getenv("MODEL_VISION", "gpt-4o")

# ─── Categorías válidas (deben coincidir con el Excel/Sheet) ────
CAT_INGRESOS = [
    "Nomina", "Freelance/Consultoria", "Alquiler cobrado", "Dividendos",
    "Venta de activo", "Devolucion/Reembolso", "Bono/Extra",
    "Regalo recibido", "Otros ingresos"
]
CAT_GASTOS = [
    "Vivienda (alquiler/hipoteca)", "Suministros (luz/agua/gas)",
    "Alimentacion/Supermercado", "Restaurantes/Bares",
    "Transporte (gasolina/parking)", "Transporte publico",
    "Suscripciones digitales", "Ropa/Calzado", "Salud/Farmacia",
    "Educacion/Formacion", "Ocio/Entretenimiento", "Viajes/Vacaciones",
    "Regalos dados", "Seguros", "Hogar (muebles/electrodomesticos)",
    "Mantenimiento/Reparaciones", "Ahorro aportado", "Inversion aportada",
    "Retirada de hucha",   # gasto especial: se guarda con importe NEGATIVO (resta de la hucha)
    "Otros gastos"
]
# Lista completa de categorias (para el desplegable de validacion de la columna C)
ALL_CATS = CAT_INGRESOS + CAT_GASTOS

METODOS_PAGO = [
    "Efectivo", "Tarjeta debito", "Tarjeta credito",
    "Transferencia", "Bizum", "Domiciliacion"
]
HUCHAS = [
    "Fondo de emergencia", "Vacaciones", "Coche", "Formacion",
    "Navidad", "Proyecto especial", "Inversion inicial", "Libre"
]
TIPOS_ACTIVO = [
    "ETF", "Fondo indexado", "Accion", "Cripto", "Bono", "Otro"
]


def validate():
    """Valida que todas las credenciales críticas estén presentes."""
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not AUTHORIZED_CHAT_ID:
        missing.append("AUTHORIZED_CHAT_ID")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not GOOGLE_SHEET_ID:
        missing.append("GOOGLE_SHEET_ID")
    if not GOOGLE_CREDENTIALS:
        missing.append("GOOGLE_CREDENTIALS_JSON")
    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")
