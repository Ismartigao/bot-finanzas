"""Migracion/reparacion (una sola vez) para las RETIRADAS DE HUCHA.

Hace dos cosas:
  1. Fija la formula de saldo (col D, filas 5-12) de la hoja HUCHAS a la SUMA
     TOTAL de la columna F del TRACKER por hucha. Asi las aportaciones (importe
     positivo) suman y las retiradas (importe NEGATIVO) restan automaticamente.
         =SUMIF(TRACKER!H3:H302; A{fila}; TRACKER!F3:F302)
  2. Actualiza la validacion de datos (desplegable) de la columna C del TRACKER
     (categorias) para incluir todas las de config.ALL_CATS, incluida
     "Retirada de hucha".

Es idempotente: se puede ejecutar varias veces sin problema.

Uso:
    cd ~/bot-finanzas && source venv/bin/activate && python update_huchas_formula.py
"""
import config
import sheets

HUCHA_START = 5
HUCHA_END = 12
TRACKER_DATA_START = 3
TRACKER_DATA_END = 302


def _saldo_formula(row: int, sep: str) -> str:
    t = config.TRACKER_SHEET_NAME
    f = f"=SUMIF({t}!H{TRACKER_DATA_START}:H{TRACKER_DATA_END};A{row};{t}!F{TRACKER_DATA_START}:F{TRACKER_DATA_END})"
    return sheets._localize_formula(f, sep)


def fijar_formulas_saldo():
    sep = config.SHEETS_FORMULA_SEP
    ws = sheets._huchas()
    nombres = ws.get(f"A{HUCHA_START}:A{HUCHA_END}")

    actualizadas, saltadas = [], []
    for i in range(HUCHA_END - HUCHA_START + 1):
        r = HUCHA_START + i
        nombre = (nombres[i][0] if i < len(nombres) and nombres[i] else "").strip()
        if not nombre:
            saltadas.append(r)
            continue
        ws.update(
            values=[[_saldo_formula(r, sep)]],
            range_name=f"D{r}",
            value_input_option="USER_ENTERED",
        )
        actualizadas.append((r, nombre))

    print(f"\n[OK] Formulas de saldo actualizadas ({len(actualizadas)}):")
    for r, n in actualizadas:
        print(f"   fila {r}: {n}")
    if saltadas:
        print(f"[SKIP] Filas vacias: {saltadas}")


def actualizar_desplegable_categorias():
    """Pone la lista de validacion de datos de la columna C (categorias)."""
    ws = sheets._tracker()
    sh = ws.spreadsheet
    sheet_id = ws.id

    valores = [{"userEnteredValue": c} for c in config.ALL_CATS]
    request = {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": TRACKER_DATA_START - 1,  # 0-based -> fila 3
                "endRowIndex": TRACKER_DATA_END,          # exclusivo
                "startColumnIndex": 2,                    # col C (0-based)
                "endColumnIndex": 3,
            },
            "rule": {
                "condition": {"type": "ONE_OF_LIST", "values": valores},
                "strict": False,        # solo avisa, no bloquea
                "showCustomUi": True,   # muestra el desplegable
            },
        }
    }
    sh.batch_update({"requests": [request]})
    print(f"\n[OK] Desplegable de categorias (col C) actualizado con {len(config.ALL_CATS)} categorias.")
    print("     Incluye 'Retirada de hucha'.")


def main():
    print("Reparando hoja para retiradas de hucha...")
    fijar_formulas_saldo()
    try:
        actualizar_desplegable_categorias()
    except Exception as e:
        print(f"\n[AVISO] No se pudo actualizar el desplegable automaticamente: {e}")
        print("        Puedes añadir 'Retirada de hucha' a mano: Datos > Validacion de datos en la columna Categoria.")
    print("\nListo. Las retiradas (importe negativo) restaran del saldo de la hucha.")


if __name__ == "__main__":
    main()
