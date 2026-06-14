"""Diagnostico (solo lectura): muestra como llegan las filas del TRACKER del mes
indicado, en formato FORMATEADO y SIN FORMATO (numero de serie), para entender
por que el /resumen las cuenta o no.

Uso:
    python diagnose_resumen.py          # mes actual
    python diagnose_resumen.py 6 2026   # junio 2026
"""
import sys
import datetime

import config
import sheets
from sheets import DATA_START_ROW, DATA_END_ROW, _cell_to_date, _cell_to_float


def main():
    hoy = datetime.date.today()
    month = int(sys.argv[1]) if len(sys.argv) > 1 else hoy.month
    year = int(sys.argv[2]) if len(sys.argv) > 2 else hoy.year

    ws = sheets._tracker()
    rng = f"A{DATA_START_ROW}:K{DATA_END_ROW}"
    fmt = ws.get(rng, value_render_option="FORMATTED_VALUE")
    unf = ws.get(rng, value_render_option="UNFORMATTED_VALUE")

    print(f"Buscando filas de {month:02d}/{year}...\n")
    encontradas = 0
    ingresos = gastos = 0.0
    for i in range(len(unf)):
        ru = (unf[i] or [])
        rf = (fmt[i] or [])
        if len(ru) < 6:
            continue
        fecha = _cell_to_date(ru[0])
        marca = ""
        if fecha and fecha.month == month and fecha.year == year:
            marca = "  <== CUENTA"
            encontradas += 1
            tipo = str(ru[1]).strip().upper()
            imp = _cell_to_float(ru[5])
            if tipo == "INGRESO":
                ingresos += imp
            elif tipo == "GASTO":
                gastos += imp
        # Mostrar solo filas con algo en la fecha
        if ru and str(ru[0]).strip():
            r_num = DATA_START_ROW + i
            print(f"fila {r_num}: fmt_fecha='{rf[0] if rf else ''}'  "
                  f"raw_fecha={ru[0]!r}  -> parse={fecha}  "
                  f"tipo={str(ru[1]).strip() if len(ru) > 1 else ''}  "
                  f"importe_raw={ru[5] if len(ru) > 5 else ''}{marca}")

    print(f"\nFilas que cuentan para {month:02d}/{year}: {encontradas}")
    print(f"Ingresos={ingresos:.2f}  Gastos(brutos)={gastos:.2f}")


if __name__ == "__main__":
    main()
