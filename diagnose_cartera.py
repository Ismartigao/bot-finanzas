"""Diagnostico: muestra que hay realmente en la cartera (filas 5-19) sin
modificar nada. Imprime para cada fila el valor FORMATEADO, el valor
NUMERICO (unformatted) y la FORMULA de las columnas A-H.
"""
import sheets
from sheets import INV_POS_START, INV_POS_END

LETRAS = ["A", "B", "C", "D", "E", "F", "G", "H"]
NOMBRES = ["Activo", "Tipo", "Ticker", "Particip(D)", "PrecMedio(E)",
           "PrecActual(F)", "Coste(G)", "Valor(H)"]


def _get(ws, rng, render):
    try:
        return ws.get(rng, value_render_option=render)
    except Exception as e:
        print(f"  (error leyendo {rng} con {render}: {e})")
        return []


def main():
    ws = sheets._inversiones()
    rng = f"A{INV_POS_START}:H{INV_POS_END}"
    formatted = _get(ws, rng, "FORMATTED_VALUE")
    unform = _get(ws, rng, "UNFORMATTED_VALUE")
    formula = _get(ws, rng, "FORMULA")

    for i in range(len(formatted)):
        fr = (formatted[i] or []) + [""] * (8 - len(formatted[i] or []))
        un = (unform[i] if i < len(unform) else []) or []
        un = un + [""] * (8 - len(un))
        fo = (formula[i] if i < len(formula) else []) or []
        fo = fo + [""] * (8 - len(fo))
        activo = str(fr[0]).strip()
        if not activo:
            continue
        r = INV_POS_START + i
        print(f"\n=== Fila {r}: {activo} ===")
        for c in range(8):
            print(f"  {LETRAS[c]} {NOMBRES[c]:14} | fmt='{fr[c]}'  num='{un[c]}'  formula='{fo[c]}'")


if __name__ == "__main__":
    main()
