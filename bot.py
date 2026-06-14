"""Bot de Telegram para registrar movimientos en Google Sheets.
Comandos:
  /start, /help         - ayuda
  /resumen              - KPIs del mes actual
  /huchas               - progreso de huchas
  /categoria <nombre>   - total mes en esa categoria
  /ultimos              - ultimos 10 movimientos
  /deshacer             - borra el ultimo movimiento anadido
Mensajes de texto libre y fotos de tickets se parsean automaticamente.
"""
import asyncio
import datetime
import json
import logging
import uuid
from io import BytesIO

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import pytz

import config
import parser
import sheets

# ─── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot-finanzas")

# ─── Estado en memoria ───────────────────────────────────────────
# Guarda los movimientos pendientes de confirmar (y el último confirmado para deshacer).
pending: dict[str, dict] = {}
last_written_row: dict[int, int] = {}  # chat_id -> row


def _is_authorized(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == config.AUTHORIZED_CHAT_ID


async def _reject(update: Update):
    log.warning(f"Acceso denegado: chat_id={update.effective_user.id if update.effective_user else '?'}")
    if update.message:
        await update.message.reply_text("No estas autorizado para usar este bot.")


# ─── Comandos ────────────────────────────────────────────────────
async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)
    msg = (
        "Hola! Soy tu bot de control financiero.\n\n"
        "Escribe gastos o ingresos en lenguaje natural. Ejemplos:\n"
        "  - 35 en el merca con tarjeta\n"
        "  - ayer 12 euros de farmacia bizum\n"
        "  - nomina 2400\n"
        "  - 150 a la hucha de vacaciones\n\n"
        "Tambien puedes enviar una FOTO: un ticket de compra (lo registro como gasto)\n"
        "o una captura de compra(s) de fondos/ETFs (la analizo y anado cada inversion).\n\n"
        "Inversiones (compras): envia p.ej. 'compra 5 IWDA a 82 en investor' y lo anadire\n"
        "a la hoja INVERSIONES (posicion + historial) y al TRACKER como gasto.\n\n"
        "Comandos:\n"
        "/resumen [mes] - KPIs del mes (ej: /resumen 4 = abril)\n"
        "/huchas - progreso de huchas\n"
        "/cartera - posiciones actuales de inversion\n"
        "/actualizar - refresca precio de TODOS los fondos indexados (Morningstar)\n"
        "/precio <activo> <valor> - actualizar precio de un activo concreto a mano\n"
        "  (ETFs/cripto se actualizan solos via GOOGLEFINANCE)\n"
        "/categoria <nombre> - gasto del mes en esa categoria\n"
        "/ultimos - ultimos 10 movimientos\n"
        "/deshacer - borra el ultimo movimiento del TRACKER\n"
        "/help - esta ayuda"
    )
    await update.message.reply_text(msg)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


async def cmd_resumen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)
    tz = pytz.timezone(config.TIMEZONE)
    now = datetime.datetime.now(tz)

    # /resumen [mes] -> mes anterior. Sin argumento = mes actual.
    year, month = now.year, now.month
    if ctx.args:
        try:
            m = int(ctx.args[0])
        except ValueError:
            return await update.message.reply_text(
                "Uso: /resumen [mes]\nEjemplo: /resumen 4 (abril)"
            )
        if not 1 <= m <= 12:
            return await update.message.reply_text("El mes debe ser un numero del 1 al 12.")
        month = m
        # Si pides un mes futuro respecto a hoy, se asume el del año pasado.
        year = now.year if m <= now.month else now.year - 1

    await update.message.chat.send_action(constants.ChatAction.TYPING)
    try:
        summary = await asyncio.to_thread(sheets.month_summary, year, month)
    except Exception as e:
        log.exception("Error leyendo resumen")
        return await update.message.reply_text(f"Error: {e}")

    ing = summary["ingresos"]
    gas = summary["gastos"]
    bal = summary["balance"]
    tasa = summary["tasa_ahorro"] * 100
    ret_hucha = summary.get("retiradas_hucha", 0.0)

    top = sorted(summary["por_categoria"].items(), key=lambda x: -x[1])[:5]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    mes_txt = meses[month - 1]

    msg = (
        f"Resumen de {mes_txt} {year}\n\n"
        f"Ingresos:  {_fmt_eur(ing)}\n"
        f"Gastos:    {_fmt_eur(gas)}\n"
        f"Balance:   {_fmt_eur(bal)}\n"
        f"Tasa ahorro: {tasa:.1f}%\n"
    )
    if ret_hucha > 0:
        msg += f"Retiradas de hucha: {_fmt_eur(ret_hucha)} (compensan gastos ya ahorrados)\n"
    msg += "\nTop gastos por categoria:\n"
    if top:
        for c, v in top:
            msg += f"  - {c}: {_fmt_eur(v)}\n"
    else:
        msg += "  (sin datos)"
    await update.message.reply_text(msg)


async def cmd_huchas(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)
    await update.message.chat.send_action(constants.ChatAction.TYPING)
    try:
        data = await asyncio.to_thread(sheets.huchas_summary)
    except Exception as e:
        log.exception("Error leyendo huchas")
        return await update.message.reply_text(f"Error: {e}")

    if not data:
        return await update.message.reply_text("No hay huchas configuradas.")

    lines = ["Tus huchas:\n"]
    for h in data:
        lines.append(f"- {h['nombre']}: {h['saldo']} / {h['objetivo']} ({h['porcentaje']}) {h['estado']}")
    await update.message.reply_text("\n".join(lines))


async def cmd_categoria(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)
    if not ctx.args:
        return await update.message.reply_text("Uso: /categoria <nombre parcial>\nEjemplo: /categoria aliment")

    nombre = " ".join(ctx.args)
    tz = pytz.timezone(config.TIMEZONE)
    now = datetime.datetime.now(tz)
    try:
        total = await asyncio.to_thread(sheets.category_summary, now.year, now.month, nombre)
    except Exception as e:
        log.exception("Error en categoria")
        return await update.message.reply_text(f"Error: {e}")

    await update.message.reply_text(
        f"Total gastado este mes en '{nombre}': {_fmt_eur(total)}"
    )


async def cmd_ultimos(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)
    await update.message.chat.send_action(constants.ChatAction.TYPING)
    try:
        rows = await asyncio.to_thread(sheets.get_last_n_movements, 10)
    except Exception as e:
        log.exception("Error en ultimos")
        return await update.message.reply_text(f"Error: {e}")

    if not rows:
        return await update.message.reply_text("No hay movimientos registrados.")

    lines = ["Ultimos 10 movimientos:\n"]
    for r in rows:
        tipo = r["tipo"][:3].upper()
        lines.append(f"{r['fecha']} [{tipo}] {r['descripcion'] or r['categoria']}: {r['importe']}")
    await update.message.reply_text("\n".join(lines))


async def cmd_actualizar(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    """Refresca el precio de los fondos indexados (por ISIN) consultando Morningstar.es.
    No hace falta pasar argumentos: actualiza todos los activos de la hoja INVERSIONES."""
    if not _is_authorized(update):
        return await _reject(update)
    aviso = await update.message.reply_text(
        "Buscando precios en Morningstar... esto puede tardar 30-60s."
    )
    await update.message.chat.send_action(constants.ChatAction.TYPING)
    try:
        res = await asyncio.to_thread(sheets.refresh_fund_prices)
    except Exception as e:
        log.exception("Error en /actualizar")
        return await aviso.edit_text(f"Error: {e}")

    lines: list[str] = []
    if res["updated"]:
        lines.append("Actualizados:")
        for u in res["updated"]:
            lines.append(f"  ✓ {u['activo']}: {_fmt_eur(u['precio'])}")
    if res["skipped"]:
        lines.append("")
        lines.append("Sin tocar (auto via GOOGLEFINANCE u otros):")
        for s in res["skipped"]:
            lines.append(f"  • {s['activo']} — {s['razon']}")
    if res["failed"]:
        lines.append("")
        lines.append("No encontrados en Morningstar:")
        for f in res["failed"]:
            isin = f.get("isin", "")
            lines.append(f"  ✗ {f['activo']} ({isin})")
        lines.append("  (puedes ponerlos manualmente con /precio NOMBRE VALOR)")
    if not lines:
        lines = ["No hay posiciones en INVERSIONES."]

    await aviso.edit_text("\n".join(lines))


async def cmd_precio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Actualiza el precio actual de una posicion: /precio <nombre> <valor>."""
    if not _is_authorized(update):
        return await _reject(update)
    if not ctx.args or len(ctx.args) < 2:
        return await update.message.reply_text(
            "Uso: /precio <nombre parcial> <valor>\n"
            "Ejemplo: /precio Vanguard Global 195.42\n"
            "         /precio IWDA 88,50"
        )

    # El ULTIMO token es el precio; el resto es el nombre.
    precio_str = ctx.args[-1].replace(",", ".").replace("€", "").strip()
    try:
        precio = float(precio_str)
    except ValueError:
        return await update.message.reply_text(
            f"No entiendo el precio '{ctx.args[-1]}'. Debe ser un numero."
        )
    if precio <= 0:
        return await update.message.reply_text("El precio debe ser positivo.")

    nombre = " ".join(ctx.args[:-1]).strip()
    if not nombre:
        return await update.message.reply_text("Falta el nombre del activo.")

    await update.message.chat.send_action(constants.ChatAction.TYPING)
    try:
        res = await asyncio.to_thread(sheets.update_price, nombre, precio)
    except Exception as e:
        log.exception("Error actualizando precio")
        return await update.message.reply_text(f"Error: {e}")

    if not res.get("found"):
        return await update.message.reply_text(
            f"No encontre ninguna posicion que coincida con '{nombre}'.\n"
            f"Usa /cartera para ver los nombres exactos."
        )

    prev = res.get("precio_anterior", 0)
    msg = (
        f"Precio actualizado: {res['activo']} (fila {res['row']})\n"
        f"  Nuevo:    {_fmt_eur(res['precio_nuevo'])}"
    )
    if prev:
        msg += f"\n  Anterior: {_fmt_eur(prev)}"
    await update.message.reply_text(msg)


async def cmd_cartera(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)
    await update.message.chat.send_action(constants.ChatAction.TYPING)
    try:
        posiciones = await asyncio.to_thread(sheets.list_positions)
    except Exception as e:
        log.exception("Error leyendo cartera")
        return await update.message.reply_text(f"Error: {e}")

    if not posiciones:
        return await update.message.reply_text("La cartera esta vacia todavia.")

    lines = ["Tu cartera:\n"]
    for p in posiciones:
        lines.append(
            f"- {p['activo']} ({p['ticker'] or p['tipo']}): "
            f"{p['participaciones']} part. @ {p['precio_medio']} | "
            f"valor {p['valor_actual']} | G/P {p['gp']} ({p['gp_pct']})"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_deshacer(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)
    cid = update.effective_chat.id
    row = last_written_row.get(cid)
    if not row:
        return await update.message.reply_text("No hay ningun movimiento reciente para deshacer.")
    try:
        await asyncio.to_thread(sheets.delete_row, row)
        last_written_row.pop(cid, None)
        await update.message.reply_text(f"Movimiento de la fila {row} eliminado.")
    except Exception as e:
        log.exception("Error al deshacer")
        await update.message.reply_text(f"Error: {e}")


# ─── Handlers principales ────────────────────────────────────────
async def handle_text(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)
    texto = update.message.text.strip()
    if not texto:
        return

    await update.message.chat.send_action(constants.ChatAction.TYPING)
    try:
        data = await asyncio.to_thread(parser.parse_text, texto)
    except Exception as e:
        log.exception("Error parseando texto")
        return await update.message.reply_text(f"No pude entender el mensaje: {e}")

    await _send_confirmation(update, data)


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return await _reject(update)

    await update.message.chat.send_action(constants.ChatAction.UPLOAD_PHOTO)
    # Coger la foto de mayor resolución
    photo = update.message.photo[-1]
    tg_file = await ctx.bot.get_file(photo.file_id)
    buf = BytesIO()
    await tg_file.download_to_memory(buf)
    image_bytes = buf.getvalue()

    try:
        data = await asyncio.to_thread(parser.parse_photo, image_bytes)
    except Exception as e:
        log.exception("Error parseando imagen")
        return await update.message.reply_text(f"No pude leer la imagen: {e}")

    # Imagen de inversion: puede traer VARIAS compras -> una confirmacion por compra.
    if data.get("clasif") == "inversion":
        compras = data.get("compras") or []
        if not compras:
            return await update.message.reply_text(
                "He visto una confirmacion de inversion pero no pude leer los datos. "
                "Reenvia la imagen mas nitida o registralo a mano."
            )
        await update.message.reply_text(
            f"He detectado {len(compras)} compra(s) de inversion. Confirma cada una:"
        )
        for c in compras:
            c["notas"] = "[captura inversion]"
            await _send_investment_confirmation(update, c)
        return

    # Ticket de gasto normal
    data["notas"] = (data.get("notas", "") + " [ticket foto]").strip()
    await _send_confirmation(update, data, es_ticket=True)


async def _send_confirmation(update: Update, data: dict, es_ticket: bool = False):
    """Envía mensaje con botones Si/Editar/Cancelar."""
    if data.get("es_inversion"):
        return await _send_investment_confirmation(update, data)

    pid = uuid.uuid4().hex[:10]
    pending[pid] = data

    # Retirada de hucha: si no se detecto la hucha, pedirla; si si, confirmar.
    if (data.get("categoria") or "").strip() == "Retirada de hucha":
        data["tipo"] = "GASTO"
        if not data.get("hucha"):
            return await update.message.reply_text(
                "De que hucha sale el dinero?", reply_markup=_ask_hucha_kb(pid)
            )
        return await update.message.reply_text(
            _retirada_confirm_text(data), reply_markup=_retirada_confirm_kb(pid)
        )

    tipo_emoji = "+" if data["tipo"] == "INGRESO" else "-"
    fecha = data["fecha"].strftime("%d/%m/%Y") if isinstance(data["fecha"], datetime.date) else data["fecha"]
    confianza_pct = int(data["confianza"] * 100)

    lineas = [
        ("Ticket procesado. " if es_ticket else "") + "Voy a anotar:",
        "",
        f"Tipo:       {tipo_emoji} {data['tipo']}",
        f"Importe:    {_fmt_eur(data['importe'])}",
        f"Categoria:  {data['categoria'] or '(sin definir)'}",
        f"Descripcion: {data['descripcion'] or '(vacio)'}",
        f"Metodo:     {data['metodo_pago']}",
        f"Fecha:      {fecha}",
    ]
    if data.get("hucha"):
        lineas.append(f"Hucha:      {data['hucha']}")
    if data.get("subcategoria"):
        lineas.append(f"Subcat.:    {data['subcategoria']}")

    lineas.append("")
    if confianza_pct < 70:
        lineas.append(f"Confianza del parser: {confianza_pct}% - revisa bien antes de guardar.")
    else:
        lineas.append(f"Confianza: {confianza_pct}%")

    kb = [[
        InlineKeyboardButton("Guardar", callback_data=f"ok:{pid}"),
        InlineKeyboardButton("Cancelar", callback_data=f"no:{pid}"),
    ]]
    # Si es un INGRESO que no se ha detectado ya como retirada de hucha,
    # ofrecer boton de corrección rapida.
    if data["tipo"] == "INGRESO" and data.get("categoria") != "Retirada de hucha":
        kb.append([
            InlineKeyboardButton("💰 Es retirada de hucha", callback_data=f"ret_hucha:{pid}"),
        ])
    await update.message.reply_text(
        "\n".join(lineas),
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def _send_investment_confirmation(update: Update, data: dict):
    """Mensaje de confirmacion especifico para compras de inversion."""
    pid = uuid.uuid4().hex[:10]
    pending[pid] = data

    fecha = data["fecha"].strftime("%d/%m/%Y") if isinstance(data["fecha"], datetime.date) else data["fecha"]
    confianza_pct = int(data.get("confianza", 0) * 100)

    lineas = [
        "Compra de inversion detectada. Voy a registrar:",
        "",
        f"Activo:       {data.get('activo', '(sin nombre)')}",
    ]
    if data.get("tipo_activo"):
        lineas.append(f"Tipo activo:  {data['tipo_activo']}")
    if data.get("ticker"):
        lineas.append(f"Ticker/ISIN:  {data['ticker']}")
    lineas.extend([
        f"Cantidad:     {_fmt_part(data.get('cantidad', 0))} participaciones",
        f"Precio unit.: {_fmt_eur(data.get('precio', 0))}",
        f"Importe:      {_fmt_eur(data.get('importe', 0))}",
    ])
    if data.get("broker"):
        lineas.append(f"Broker:       {data['broker']}")
    lineas.append(f"Fecha:        {fecha}")
    lineas.append("")
    lineas.append("Se anadira a INVERSIONES (posicion + historial) y al TRACKER.")
    lineas.append("")
    if confianza_pct < 70:
        lineas.append(f"Confianza: {confianza_pct}% - revisa bien.")
    else:
        lineas.append(f"Confianza: {confianza_pct}%")

    kb = [[
        InlineKeyboardButton("Guardar", callback_data=f"ok:{pid}"),
        InlineKeyboardButton("Cancelar", callback_data=f"no:{pid}"),
    ]]
    await update.message.reply_text(
        "\n".join(lineas),
        reply_markup=InlineKeyboardMarkup(kb),
    )


def _ask_hucha_kb(pid: str) -> InlineKeyboardMarkup:
    """Teclado para elegir de que hucha se retira el dinero.
    Lee los nombres EN VIVO de la hoja HUCHAS y guarda la lista resuelta en el
    pending, para que el callback set_hucha resuelva por indice de forma fiable."""
    try:
        nombres = sheets.list_hucha_names()
    except Exception:
        nombres = list(config.HUCHAS)
    if pid in pending:
        pending[pid]["_hucha_opts"] = nombres
    botones = []
    fila = []
    for i, h in enumerate(nombres):
        fila.append(InlineKeyboardButton(h, callback_data=f"set_hucha:{pid}:{i}"))
        if len(fila) == 2:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
    botones.append([InlineKeyboardButton("Cancelar", callback_data=f"no:{pid}")])
    return InlineKeyboardMarkup(botones)


def _retirada_confirm_text(data: dict) -> str:
    """Texto de confirmacion de una retirada de hucha."""
    fecha = data["fecha"].strftime("%d/%m/%Y") if isinstance(data["fecha"], datetime.date) else data["fecha"]
    lineas = [
        "Retirada de hucha. Voy a anotar:",
        "",
        f"Tipo:       - GASTO (retirada)",
        f"Importe:    {_fmt_eur(data['importe'])} (sale de la hucha)",
        f"Categoria:  Retirada de hucha",
        f"Hucha:      {data.get('hucha') or '(sin hucha - no restara de ninguna)'}",
        f"Descripcion: {data['descripcion'] or '(vacio)'}",
        f"Fecha:      {fecha}",
        "",
        "No cuenta como ingreso; compensa los gastos que ya ahorraste.",
    ]
    return "\n".join(lineas)


def _retirada_confirm_kb(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Guardar", callback_data=f"ok:{pid}"),
        InlineKeyboardButton("Cancelar", callback_data=f"no:{pid}"),
    ]])


async def handle_callback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_authorized(update):
        return await query.edit_message_text("No autorizado.")

    action, rest = query.data.split(":", 1)

    # Correccion rapida: marcar como retirada de hucha (no guarda todavia)
    if action == "ret_hucha":
        pid = rest
        data = pending.get(pid)
        if not data:
            return await query.edit_message_text("Este mensaje ha caducado. Envialo de nuevo.")
        data["categoria"] = "Retirada de hucha"
        data["tipo"] = "GASTO"
        if not data.get("hucha"):
            # No se detecto la hucha: pedir al usuario que la elija.
            return await query.edit_message_text(
                "De que hucha sale el dinero?", reply_markup=_ask_hucha_kb(pid)
            )
        return await query.edit_message_text(
            _retirada_confirm_text(data), reply_markup=_retirada_confirm_kb(pid)
        )

    # El usuario elige la hucha de la lista
    if action == "set_hucha":
        pid, idx = rest.split(":", 1)
        data = pending.get(pid)
        if not data:
            return await query.edit_message_text("Este mensaje ha caducado. Envialo de nuevo.")
        opciones = data.get("_hucha_opts") or list(config.HUCHAS)
        try:
            data["hucha"] = opciones[int(idx)]
        except (ValueError, IndexError):
            data["hucha"] = ""
        return await query.edit_message_text(
            _retirada_confirm_text(data), reply_markup=_retirada_confirm_kb(pid)
        )

    pid = rest
    data = pending.pop(pid, None)
    if not data:
        return await query.edit_message_text("Este mensaje ha caducado. Envialo de nuevo.")

    if action == "no":
        return await query.edit_message_text("Cancelado. Nada guardado.")

    if action == "ok":
        try:
            if data.get("es_inversion"):
                res = await asyncio.to_thread(sheets.append_investment, data)
                last_written_row[query.message.chat_id] = res["tracker_row"]
                await query.edit_message_text(
                    f"Inversion registrada:\n"
                    f"- INVERSIONES fila {res['inv_row']} ({res['accion']})\n"
                    f"- Historial fila {res['hist_row']}\n"
                    f"- TRACKER fila {res['tracker_row']} ({_fmt_eur(data['importe'])})\n\n"
                    f"/deshacer borra solo la entrada del TRACKER."
                )
            else:
                row = await asyncio.to_thread(sheets.append_movement, data)
                last_written_row[query.message.chat_id] = row
                fecha = data["fecha"].strftime("%d/%m/%Y") if isinstance(data["fecha"], datetime.date) else data["fecha"]
                await query.edit_message_text(
                    f"Guardado en la fila {row}.\n"
                    f"{data['tipo']} de {_fmt_eur(data['importe'])} "
                    f"en {data['categoria']} ({fecha}).\n\n"
                    f"Usa /deshacer si te has equivocado."
                )
        except Exception as e:
            log.exception("Error guardando")
            await query.edit_message_text(f"Error al guardar: {e}")


def _fmt_part(v) -> str:
    """Formatea participaciones con precision completa, sin ceros sobrantes."""
    try:
        s = f"{float(v):.8f}".rstrip("0").rstrip(".")
        return s if s else "0"
    except (ValueError, TypeError):
        return str(v)


def _fmt_eur(v) -> str:
    try:
        v = float(v)
    except (ValueError, TypeError):
        return str(v)
    s = f"{v:,.2f}"
    # Formato europeo: miles con punto, decimales con coma
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


# ─── Main ────────────────────────────────────────────────────────
def main():
    config.validate()
    log.info("Configuracion validada. Iniciando bot...")

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("huchas", cmd_huchas))
    app.add_handler(CommandHandler("cartera", cmd_cartera))
    app.add_handler(CommandHandler("precio", cmd_precio))
    app.add_handler(CommandHandler("actualizar", cmd_actualizar))
    app.add_handler(CommandHandler("categoria", cmd_categoria))
    app.add_handler(CommandHandler("ultimos", cmd_ultimos))
    app.add_handler(CommandHandler("deshacer", cmd_deshacer))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bot arrancado. Esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
