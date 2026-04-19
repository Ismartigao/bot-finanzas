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

_raw_creds = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
try:
    GOOGLE_CREDENTIALS = json.loads(_raw_creds) if _raw_creds else None
except json.JSONDecodeError as e:
    raise RuntimeError(f"GOOGLE_CREDENTIALS_JSON no es un JSON valido: {e}")

# ─── Otros ───────────────────────────────────────────────────────
TIMEZONE = os.getenv("TIMEZONE", "Europe/Madrid")
MODEL_TEXT = os.getenv("MODEL_TEXT", "gpt-4o-mini")
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
    "Otros gastos"
]
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
