"""Migracion (una sola vez): actualiza la formula de saldo (col D) de cada hucha
para que reste las 'Retirada de hucha' ademas de sumar las aportaciones.

Formula resultante en cada celda Dx (filas 5-12):
  =SUMIFS(TRACKER!F:F;TRACKER!H:H;Ax;TRACKER!C:C;"Ahorro aportado")
  -SUMIFS(TRACKER!F:F;TRACKER!H:H;Ax;TRACKER!C:C;"Retirada de hucha")

Uso:
    cd ~/bot-finanzas && source venv/bin/activate && python update_huchas_formula.py
"""
import config
import sheets

HUCHA_START = 5
HUCHA_END = 12


def _saldo_formula(row: int, sep: str) -> str:
    t = config.TRACKER_SHEET_NAME
    f = (
        f"=SUMIFS({t}!F:F{sep}{t}!H:H{sep}A{row}{sep}{t}!C:C{sep}\"Ahorro aportado\")"
        f"-SUMIFS({t}!F:F{sep}{t}!H:H{sep}A{row}{sep}{t}!C:C{sep}\"Retirada de hucha\")"
    )
    return f


def main():
    sep = config.SHEETS_FORMULA_SEP
    ws = sheets._huchas()

    # Leer nombres de huchas activas (col A)
    nombres = ws.get(f"A{HUCHA_START}:A{HUCHA_END}")

    actualizadas = []
    saltadas = []

    for i in range(HUCHA_END - HUCHA_START + 1):
        r = HUCHA_START + i
        nombre = (nombres[i][0] if i < len(nombres) and nombres[i] else "").strip()
        if not nombre:
            saltadas.append(r)
            continue

        formula = _saldo_formula(r, sep)
        ws.update(
            values=[[formula]],
            range_name=f"D{r}",
            value_input_option="USER_ENTERED",
        )
        actualizadas.append((r, nombre))

    print("\n========== RESULTADO ==========")
    print(f"Separador usado: '{sep}'")
    print(f"\n[OK] Formulas actualizadas ({len(actualizadas)}):")
    for r, n in actualizadas:
        print(f"   fila {r}: {n}")
    if saltadas:
        print(f"\n[SKIP] Filas vacias (sin hucha): {saltadas}")
    print("\nListo. El saldo de cada hucha ahora descuenta las retiradas automaticamente.")


if __name__ == "__main__":
    main()
