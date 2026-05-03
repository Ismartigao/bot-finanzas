"""Capa de acceso a Google Sheets para lectura y escritura del TRACKER."""
import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Columnas del TRACKER (en este orden, igual que el Excel)
# A: Fecha | B: Tipo | C: Categoria | D: Subcategoria | E: Descripcion
# F: Importe | G: Metodo pago | H: Hucha vinculada | I: Origen presupuesto
# J: Estado | K: Notas
COLUMNS = [
    "fecha", "tipo", "categoria", "subcategoria", "descripcion",
    "importe", "metodo_pago", "hucha", "origen_presupuesto", "estado", "notas"
]

# La tabla de datos empieza en la fila 3 (filas 1-2 son título y cabeceras)
DATA_START_ROW = 3
DATA_END_ROW = 302  # última fila preparada del Excel original

# Hoja INVERSIONES
INV_POS_START = 5      # primera fila de posiciones
INV_POS_END = 19       # última fila de posiciones preparada
INV_HIST_START = 39    # primera fila del historial de aportaciones
INV_HIST_END = 60      # última fila del historial


def _client() -> gspread.Client:
    creds = Credentials.from_service_account_info(
        config.GOOGLE_CREDENTIALS, scopes=SCOPES
    )
    return gspread.authorize(creds)


def _tracker():
    gc = _client()
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    return sh.worksheet(config.TRACKER_SHEET_NAME)


def _huchas():
    gc = _client()
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    return sh.worksheet(config.HUCHAS_SHEET_NAME)


def _inversiones():
    gc = _client()
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    return sh.worksheet(config.INVERSIONES_SHEET_NAME)


def _find_first_empty_row(ws) -> int:
    """Busca la primera fila vacía en el rango de datos del TRACKER."""
    col_a = ws.col_values(1)  # columna Fecha
    for i in range(DATA_START_ROW - 1, len(col_a)):
        if not col_a[i].strip():
            return i + 1
    # Si todas las filas del rango tienen datos, añade al final
    return max(len(col_a) + 1, DATA_START_ROW)


def append_movement(data: dict) -> int:
    """
    Añade un movimiento al TRACKER. Devuelve el número de fila donde se escribió.
    `data` debe tener las claves definidas en COLUMNS.
    """
    ws = _tracker()
    row_num = _find_first_empty_row(ws)

    # Formatear fecha: gspread acepta string en formato ISO o dd/mm/yyyy
    fecha = data.get("fecha")
    if isinstance(fecha, datetime.date):
        fecha_str = fecha.strftime("%d/%m/%Y")
    else:
        fecha_str = str(fecha) if fecha else ""

    # Importe como número (sin formato, Sheets lo interpreta)
    importe = data.get("importe", 0)
    try:
        importe = float(importe)
    except (ValueError, TypeError):
        importe = 0.0

    row = [
        fecha_str,
        data.get("tipo", ""),
        data.get("categoria", ""),
        data.get("subcategoria", ""),
        data.get("descripcion", ""),
        importe,
        data.get("metodo_pago", ""),
        data.get("hucha", ""),
        data.get("origen_presupuesto", "") or data.get("categoria", ""),
        data.get("estado", "REAL"),
        data.get("notas", ""),
    ]

    # Escribir la fila (USER_ENTERED para que respete formato de fecha/número)
    rng = f"A{row_num}:K{row_num}"
    ws.update(rng, [row], value_input_option="USER_ENTERED")
    return row_num


def delete_row(row_num: int) -> None:
    """Borra el contenido de una fila (deja la fila vacía)."""
    ws = _tracker()
    ws.batch_clear([f"A{row_num}:K{row_num}"])


def get_last_n_movements(n: int = 10) -> list[dict]:
    """Devuelve los últimos n movimientos registrados."""
    ws = _tracker()
    all_rows = ws.get(f"A{DATA_START_ROW}:K{DATA_END_ROW}")
    # Filtrar filas no vacías
    rows_with_num = [
        (DATA_START_ROW + i, r) for i, r in enumerate(all_rows)
        if r and len(r) >= 6 and r[0].strip()
    ]
    last = rows_with_num[-n:]
    result = []
    for rn, r in last:
        r = r + [""] * (11 - len(r))
        result.append({
            "row": rn,
            "fecha": r[0], "tipo": r[1], "categoria": r[2],
            "descripcion": r[4], "importe": r[5], "metodo_pago": r[6],
        })
    return result


def month_summary(year: int, month: int) -> dict:
    """Calcula ingresos, gastos, balance y tasa de ahorro del mes dado."""
    ws = _tracker()
    all_rows = ws.get(f"A{DATA_START_ROW}:K{DATA_END_ROW}")
    ingresos = 0.0
    gastos = 0.0
    por_categoria = {}

    for r in all_rows:
        if not r or len(r) < 6 or not r[0].strip():
            continue
        try:
            # Fecha puede venir como string dd/mm/yyyy
            partes = r[0].split("/")
            if len(partes) != 3:
                continue
            d, m, y = int(partes[0]), int(partes[1]), int(partes[2])
            if m != month or y != year:
                continue
        except (ValueError, IndexError):
            continue

        tipo = r[1].strip().upper()
        try:
            importe = float(str(r[5]).replace(",", ".").replace("\u20ac", "").replace(" ", ""))
        except ValueError:
            importe = 0.0

        if tipo == "INGRESO":
            ingresos += importe
        elif tipo == "GASTO":
            gastos += importe
            cat = r[2].strip()
            por_categoria[cat] = por_categoria.get(cat, 0) + importe

    balance = ingresos - gastos
    tasa = (balance / ingresos) if ingresos > 0 else 0
    return {
        "ingresos": ingresos,
        "gastos": gastos,
        "balance": balance,
        "tasa_ahorro": tasa,
        "por_categoria": por_categoria,
    }


def category_summary(year: int, month: int, categoria: str) -> float:
    """Total gastado en una categoría en un mes concreto."""
    summary = month_summary(year, month)
    # Búsqueda case-insensitive parcial
    cat_lower = categoria.lower()
    for k, v in summary["por_categoria"].items():
        if cat_lower in k.lower():
            return v
    return 0.0


# ─── Inversiones ─────────────────────────────────────────────────
def _parse_num(v) -> float:
    """Convierte una celda de Sheets (puede venir con €, comas, etc.) a float."""
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s:
        return 0.0
    s = s.replace("\u20ac", "").replace(" ", "").replace(".", "").replace(",", ".")
    # Nota: hemos quitado puntos (miles) y cambiado coma->punto (decimal).
    # Si la celda ya era "82.5" sin miles, el reemplazo anterior la destrozaria.
    # Intentar parse directo primero:
    try:
        return float(str(v).replace("\u20ac", "").replace(" ", "").replace(",", "."))
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return 0.0


def _find_position_by_name(ws, activo: str) -> Optional[int]:
    """Busca una posicion existente por coincidencia parcial en la columna A."""
    if not activo:
        return None
    rng = ws.get(f"A{INV_POS_START}:A{INV_POS_END}")
    target = activo.lower().strip()
    for i, row in enumerate(rng):
        if not row or not row[0]:
            continue
        celda = row[0].strip()
        if not celda:
            continue
        cl = celda.lower()
        if target in cl or cl in target:
            return INV_POS_START + i
    return None


def _find_first_empty_inv_row(ws) -> Optional[int]:
    rng = ws.get(f"A{INV_POS_START}:A{INV_POS_END}")
    for i in range(INV_POS_END - INV_POS_START + 1):
        if i >= len(rng) or not rng[i] or not rng[i][0].strip():
            return INV_POS_START + i
    return None


def _find_first_empty_hist_row(ws) -> Optional[int]:
    rng = ws.get(f"A{INV_HIST_START}:A{INV_HIST_END}")
    for i in range(INV_HIST_END - INV_HIST_START + 1):
        if i >= len(rng) or not rng[i] or not rng[i][0].strip():
            return INV_HIST_START + i
    return None


def append_investment(data: dict) -> dict:
    """
    Registra una compra de inversion:
      1. Actualiza/crea la posicion en INVERSIONES (filas 5-19).
      2. Anade una linea al HISTORIAL DE APORTACIONES (filas 39-60).
      3. Anade la entrada correspondiente al TRACKER como GASTO Inversion aportada.
    Devuelve {"accion", "inv_row", "hist_row", "tracker_row"}.
    """
    ws = _inversiones()
    activo = data.get("activo", "").strip()
    cantidad = float(data.get("cantidad", 0) or 0)
    precio = float(data.get("precio", 0) or 0)
    importe = float(data.get("importe", 0) or (cantidad * precio))

    fecha = data.get("fecha")
    if isinstance(fecha, datetime.date):
        fecha_str = fecha.strftime("%d/%m/%Y")
    else:
        fecha_str = str(fecha) if fecha else ""

    # 1. Buscar posicion existente
    inv_row = _find_position_by_name(ws, activo)
    if inv_row is not None:
        # Actualizar: leer D (participaciones) y E (precio medio).
        # NO tocamos F (precio actual) para no machacar la formula GOOGLEFINANCE.
        current = ws.get(f"D{inv_row}:E{inv_row}")
        cur_part = 0.0
        cur_pmedio = 0.0
        if current and current[0]:
            fila = current[0] + [""] * (2 - len(current[0]))
            cur_part = _parse_num(fila[0])
            cur_pmedio = _parse_num(fila[1])
        nuevas_part = cur_part + cantidad
        if nuevas_part > 0:
            nuevo_pmedio = (cur_part * cur_pmedio + cantidad * precio) / nuevas_part
        else:
            nuevo_pmedio = precio
        ws.update(
            f"D{inv_row}:E{inv_row}",
            [[nuevas_part, round(nuevo_pmedio, 4)]],
            value_input_option="USER_ENTERED",
        )
        accion = "actualizada"
    else:
        # Crear nueva posicion en primera fila vacia.
        # Se escriben A-E (sin F, para preservar la formula GOOGLEFINANCE de la celda).
        inv_row = _find_first_empty_inv_row(ws)
        if inv_row is None:
            raise RuntimeError(
                f"No hay filas libres en INVERSIONES (filas {INV_POS_START}-{INV_POS_END})."
            )
        tipo_activo = data.get("tipo_activo", "") or "ETF"
        ticker = data.get("ticker", "")
        broker = data.get("broker", "")
        # A-E: datos basicos; F: queda intacta (formula GOOGLEFINANCE);
        # G-K: formulas prerrellenadas; L-M: broker + fecha 1a compra.
        ws.update(
            f"A{inv_row}:E{inv_row}",
            [[activo, tipo_activo, ticker, cantidad, precio]],
            value_input_option="USER_ENTERED",
        )
        ws.update(
            f"L{inv_row}:M{inv_row}",
            [[broker, fecha_str]],
            value_input_option="USER_ENTERED",
        )
        accion = "creada"

    # 2. Historial de aportaciones
    hist_row = _find_first_empty_hist_row(ws)
    if hist_row is not None:
        ws.update(
            f"A{hist_row}:F{hist_row}",
            [[fecha_str, activo, cantidad, precio, importe, "Compra"]],
            value_input_option="USER_ENTERED",
        )

    # 3. TRACKER — reusa append_movement pero normalizando los campos
    ticker = data.get("ticker", "")
    broker = data.get("broker", "")
    notas_parts = []
    if ticker:
        notas_parts.append(f"ticker {ticker}")
    if broker:
        notas_parts.append(f"broker {broker}")
    notas_prev = (data.get("notas") or "").strip()
    if notas_prev:
        notas_parts.append(notas_prev)

    tracker_data = dict(data)
    tracker_data["tipo"] = "GASTO"
    tracker_data["categoria"] = "Inversion aportada"
    tracker_data["subcategoria"] = data.get("tipo_activo", "") or ""
    tracker_data["descripcion"] = f"{activo} ({cantidad:g} x {precio:g} EUR)"
    tracker_data["importe"] = importe
    tracker_data["metodo_pago"] = data.get("metodo_pago", "") or "Transferencia"
    tracker_data["hucha"] = ""
    tracker_data["origen_presupuesto"] = "Inversion aportada"
    tracker_data["estado"] = "REAL"
    tracker_data["notas"] = " | ".join(notas_parts)

    tracker_row = append_movement(tracker_data)

    return {
        "accion": accion,
        "inv_row": inv_row,
        "hist_row": hist_row,
        "tracker_row": tracker_row,
    }


def list_positions() -> list[dict]:
    """Devuelve las posiciones actuales de INVERSIONES (solo con activo en col A)."""
    ws = _inversiones()
    rng = ws.get(f"A{INV_POS_START}:N{INV_POS_END}")
    result = []
    for i, r in enumerate(rng):
        r = (r or []) + [""] * (14 - len(r or []))
        if not r[0].strip():
            continue
        result.append({
            "row": INV_POS_START + i,
            "activo": r[0],
            "tipo": r[1],
            "ticker": r[2],
            "participaciones": r[3],
            "precio_medio": r[4],
            "precio_actual": r[5],
            "coste_total": r[6],
            "valor_actual": r[7],
            "gp": r[8],
            "gp_pct": r[9],
            "peso": r[10],
            "broker": r[11],
        })
    return result


def update_price(activo: str, precio: float) -> dict:
    """
    Sobreescribe la celda F (precio actual) de la posicion cuyo nombre coincida
    parcialmente con `activo`. Sustituye cualquier formula previa por el valor numerico.
    Devuelve {"found": bool, "row": int, "activo": str, "precio_anterior": float, "precio_nuevo": float}.
    """
    ws = _inversiones()
    row = _find_position_by_name(ws, activo)
    if row is None:
        return {"found": False}

    # Leer el valor previo (puede ser un numero, una formula resuelta o vacio)
    prev_cells = ws.get(f"A{row}:F{row}")
    prev_activo = ""
    prev_precio = 0.0
    if prev_cells and prev_cells[0]:
        fila = prev_cells[0] + [""] * (6 - len(prev_cells[0]))
        prev_activo = fila[0]
        prev_precio = _parse_num(fila[5])

    ws.update(
        f"F{row}:F{row}",
        [[float(precio)]],
        value_input_option="USER_ENTERED",
    )
    return {
        "found": True,
        "row": row,
        "activo": prev_activo,
        "precio_anterior": prev_precio,
        "precio_nuevo": float(precio),
    }


def huchas_summary() -> list[dict]:
    """Lee el resumen actual de las huchas."""
    ws = _huchas()
    # Huchas empiezan en fila 5, columnas A-J
    rows = ws.get("A5:J12")
    result = []
    for r in rows:
        r = r + [""] * (10 - len(r))
        if not r[0].strip():
            continue
        result.append({
            "nombre": r[0],
            "objetivo": r[1],
            "saldo": r[3],
            "porcentaje": r[4],
            "estado": r[9],
        })
    return result
