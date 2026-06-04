"""Migracion (una sola vez): convierte las columnas D (participaciones) y
E (precio medio) de la CARTERA en formulas que se autocalculan desde el
HISTORIAL DE APORTACIONES.

Es SEGURO:
  - Para cada posicion de la cartera compara las participaciones manuales
    con las que respalda el historial.
  - Si coinciden -> solo pone las formulas.
  - Si el historial NO tiene nada de ese fondo pero la cartera tiene
    participaciones -> inserta una fila "Saldo inicial" en el historial
    (para no perder la posicion) y luego pone las formulas.
  - Si hay un descuadre PARCIAL -> NO toca esa fila y la reporta para que
    la revises a mano.

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
ADD_OPS_EXCLUDE = {"venta", "dividendo"}


def _hist_net_shares(hist_rows, activo: str) -> float:
    """Participaciones netas de `activo` segun el historial (igual que la formula)."""
    target = activo.strip().lower()
    add = 0.0
    sell = 0.0
    for r in hist_rows:
        r = (r or []) + [""] * (6 - len(r or []))
        if (r[1] or "").strip().lower() != target:
            continue
        tipo = (r[5] or "").strip().lower()
        cant = _parse_num(r[2])
        if tipo == "venta":
            sell += cant
        elif tipo not in ADD_OPS_EXCLUDE:
            add += cant
    return add - sell


def _set_formulas(ws, r: int, sep: str) -> str:
    """Escribe las formulas D/E en la fila r y devuelve el valor calculado de D."""
    ws.update(
        f"D{r}:E{r}",
        [[_cartera_d_formula(r, sep), _cartera_e_formula(r, sep)]],
        value_input_option="USER_ENTERED",
    )
    val = ws.get(f"D{r}")
    if val and val[0]:
        return str(val[0][0])
    return ""


def main():
    sh, ws = sheets._inversiones_with_sh()

    # Detectar separador de formulas a partir del locale de la hoja.
    sep = config.SHEETS_FORMULA_SEP
    try:
        meta = sh.fetch_sheet_metadata()
        locale = meta.get("properties", {}).get("locale", "")
        print(f"Locale de la hoja: {locale or '(desconocido)'} | separador inicial: '{sep}'")
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
        hist_part = _hist_net_shares(hist_rows, activo)

        if abs(hist_part - manual_part) <= TOL:
            # El historial ya respalda la posicion: solo formulas.
            d_val = _set_formulas(ws, r, sep)
            # Verificar separador con la primera escritura real.
            if not sep_verified:
                if d_val.startswith("#"):
                    sep = "," if sep == ";" else ";"
                    print(f"  -> Separador '{config.SHEETS_FORMULA_SEP}' daba error; reintentando con '{sep}'")
                    d_val = _set_formulas(ws, r, sep)
                sep_verified = True
            ok.append((r, activo, manual_part))

        elif abs(hist_part) <= TOL and manual_part > TOL:
            # Historial vacio para este fondo: crear saldo inicial.
            hist_row = _find_first_empty_hist_row(ws)
            if hist_row is None:
                mismatch.append((r, activo, manual_part, hist_part, "sin filas libres en historial"))
                continue
            fecha_str = fecha1 or datetime.date.today().strftime("%d/%m/%Y")
            imp = manual_part * manual_pmedio
            ws.update(
                f"A{hist_row}:F{hist_row}",
                [[fecha_str, activo, manual_part, manual_pmedio, imp, "Saldo inicial"]],
                value_input_option="USER_ENTERED",
            )
            # refrescar historial local para los siguientes
            hist_rows = ws.get(f"A{INV_HIST_START}:F{INV_HIST_END}")
            _set_formulas(ws, r, sep)
            opened.append((r, activo, manual_part, manual_pmedio, hist_row))

        else:
            # Descuadre parcial: no tocar, reportar.
            mismatch.append((r, activo, manual_part, hist_part, "descuadre parcial"))

    # ── Informe ──
    print("\n========== RESULTADO DE LA MIGRACION ==========")
    print(f"Separador de formulas usado: '{sep}'")
    if sep != config.SHEETS_FORMULA_SEP:
        print(f"  AVISO: pon SHEETS_FORMULA_SEP={sep} en el .env para que el bot use el correcto.")

    print(f"\n[OK] Formulas aplicadas (historial ya cuadraba): {len(ok)}")
    for r, a, p in ok:
        print(f"   fila {r}: {a}  ({p:g} particip.)")

    print(f"\n[SALDO INICIAL] Posiciones sin historial -> se creo saldo inicial: {len(opened)}")
    for r, a, p, pm, hr in opened:
        print(f"   fila {r}: {a}  {p:g} x {pm:g} EUR  (historial fila {hr})")

    print(f"\n[REVISAR] Descuadres que NO se han tocado: {len(mismatch)}")
    for r, a, mp, hp, motivo in mismatch:
        print(f"   fila {r}: {a}  cartera={mp:g}  historial={hp:g}  ({motivo})")

    if mismatch:
        print("\n  -> Revisa esas filas: probablemente al historial le faltan compras")
        print("     o sobran. Cuadra el historial y vuelve a ejecutar este script.")
    print("\nListo.")


if __name__ == "__main__":
    main()
