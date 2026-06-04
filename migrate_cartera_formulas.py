"""Migracion (una sola vez): convierte las columnas D (participaciones) y
E (precio medio) de la CARTERA en formulas que se autocalculan desde el
HISTORIAL DE APORTACIONES.

Es SEGURO:
  - Para cada posicion compara las participaciones manuales con las que
    respalda el historial.
  - Si coinciden -> solo pone las formulas.
  - Si la cartera tiene MAS participaciones que el historial (compras
    antiguas no registradas, o fondo sin historial) -> inserta UNA fila
    "Saldo inicial" en el historial por la diferencia exacta, con un precio
    calculado para que tu precio medio actual se mantenga al centimo.
  - Si el historial tiene MAS que la cartera (descuadre raro) -> NO toca
    esa fila y la reporta para revision manual.

Tambien amplia el numero de filas de la hoja si hace falta.

Uso (en el servidor, con el venv activado):
    cd ~/bot-finanzas && source venv/bin/activate && python migrate_cartera_formulas.py
"""
import datetime

import config
import sheets
from sheets import (
    INV_POS_START, INV_POS_END, INV_HIST_START, INV_HIST_END,
    _parse_num, _cartera_d_formula, _cartera_e_formula,
    _find_first_empty_hist_row,
)

TOL = 0.0001
ADD_OPS_EXCLUDE = {"venta", "dividendo"}  # no cuentan como aportacion de participaciones


def _hist_stats(hist_rows, activo: str):
    """Devuelve (add_shares, add_importe, sells) del `activo` segun el historial.
    add_* = aportaciones (todo lo que no sea Venta ni Dividendo)."""
    target = activo.strip().lower()
    add_shares = add_importe = sells = 0.0
    for r in hist_rows:
        r = (r or []) + [""] * (6 - len(r or []))
        if (r[1] or "").strip().lower() != target:
            continue
        tipo = (r[5] or "").strip().lower()
        cant = _parse_num(r[2])
        imp = _parse_num(r[4])
        if tipo == "venta":
            sells += cant
        elif tipo not in ADD_OPS_EXCLUDE:
            add_shares += cant
            add_importe += imp
    return add_shares, add_importe, sells


def _ensure_rows(ws, needed: int):
    """Asegura que la hoja tiene al menos `needed` filas."""
    if ws.row_count < needed:
        ws.add_rows(needed - ws.row_count)
        print(f"Ampliadas filas de la hoja a {needed}.")


def _set_formulas(ws, r: int, sep: str) -> str:
    """Escribe las formulas D/E en la fila r y devuelve el valor calculado de D."""
    ws.update(
        values=[[_cartera_d_formula(r, sep), _cartera_e_formula(r, sep)]],
        range_name=f"D{r}:E{r}",
        value_input_option="USER_ENTERED",
    )
    val = ws.get(f"D{r}")
    if val and val[0]:
        return str(val[0][0])
    return ""


def main():
    sh, ws = sheets._inversiones_with_sh()
    _ensure_rows(ws, INV_HIST_END)

    sep = config.SHEETS_FORMULA_SEP
    try:
        meta = sh.fetch_sheet_metadata()
        locale = meta.get("properties", {}).get("locale", "")
        print(f"Locale de la hoja: {locale or '(desconocido)'} | separador: '{sep}'")
    except Exception:
        pass

    cartera = ws.get(f"A{INV_POS_START}:M{INV_POS_END}")
    hist_rows = ws.get(f"A{INV_HIST_START}:F{INV_HIST_END}")

    ok, opened, mismatch = [], [], []
    sep_verified = False

    for i, row in enumerate(cartera):
        r = INV_POS_START + i
        row = (row or []) + [""] * (13 - len(row or []))
        activo = (row[0] or "").strip()
        if not activo:
            continue

        manual_part = _parse_num(row[3])
        manual_pmedio = _parse_num(row[4])
        fecha1 = (row[12] or "").strip()

        add_shares, add_importe, sells = _hist_stats(hist_rows, activo)
        hist_part = add_shares - sells
        delta = manual_part - hist_part

        if abs(delta) <= TOL:
            # El historial ya respalda la posicion: solo formulas.
            d_val = _set_formulas(ws, r, sep)
            if not sep_verified:
                if d_val.startswith("#"):
                    sep = "," if sep == ";" else ";"
                    print(f"  Separador daba error; reintentando con '{sep}'")
                    d_val = _set_formulas(ws, r, sep)
                sep_verified = True
            ok.append((r, activo, manual_part))

        elif delta > TOL:
            # Falta parte en el historial -> crear saldo inicial por la diferencia.
            if manual_pmedio <= TOL:
                mismatch.append((r, activo, manual_part, hist_part,
                                 "falta precio medio para reconstruir"))
                continue
            denom_after = add_shares + delta            # = participaciones tras anadir delta
            importe_saldo = manual_pmedio * denom_after - add_importe
            if importe_saldo <= 0:
                mismatch.append((r, activo, manual_part, hist_part,
                                 "el historial ya suma mas coste del que implica tu precio medio"))
                continue
            precio_saldo = importe_saldo / delta

            hist_row = _find_first_empty_hist_row(ws)
            if hist_row is None:
                mismatch.append((r, activo, manual_part, hist_part, "sin filas libres en historial"))
                continue
            fecha_str = fecha1 or datetime.date.today().strftime("%d/%m/%Y")
            ws.update(
                values=[[fecha_str, activo, round(delta, 8),
                         round(precio_saldo, 6), round(importe_saldo, 2), "Saldo inicial"]],
                range_name=f"A{hist_row}:F{hist_row}",
                value_input_option="USER_ENTERED",
            )
            hist_rows = ws.get(f"A{INV_HIST_START}:F{INV_HIST_END}")  # refrescar
            _set_formulas(ws, r, sep)
            opened.append((r, activo, delta, precio_saldo, hist_row))

        else:
            # delta < 0: el historial tiene MAS que la cartera -> ambiguo, no tocar.
            mismatch.append((r, activo, manual_part, hist_part,
                             "el historial tiene mas participaciones que la cartera"))

    # ── Informe ──
    print("\n========== RESULTADO DE LA MIGRACION ==========")
    print(f"Separador de formulas usado: '{sep}'")
    if sep != config.SHEETS_FORMULA_SEP:
        print(f"  AVISO: pon SHEETS_FORMULA_SEP={sep} en el .env y reinicia el bot.")

    print(f"\n[OK] Formulas aplicadas (historial ya cuadraba): {len(ok)}")
    for r, a, p in ok:
        print(f"   fila {r}: {a}  ({p:g} particip.)")

    print(f"\n[SALDO INICIAL] Diferencia anadida al historial: {len(opened)}")
    for r, a, d, pr, hr in opened:
        print(f"   fila {r}: {a}  +{d:g} particip. a {pr:.4f} EUR  (historial fila {hr})")

    print(f"\n[REVISAR] Descuadres que NO se han tocado: {len(mismatch)}")
    for r, a, mp, hp, motivo in mismatch:
        print(f"   fila {r}: {a}  cartera={mp:g}  historial={hp:g}  ({motivo})")

    print("\nListo. Revisa la hoja: las columnas D y E de la cartera ya son formulas.")


if __name__ == "__main__":
    main()
