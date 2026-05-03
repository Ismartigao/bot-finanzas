"""Obtiene NAVs de fondos indexados desde Morningstar.es por ISIN.

GOOGLEFINANCE no soporta fondos indexados (no cotizan en mercado abierto),
solo tienen NAV diario. Aqui hacemos scraping ligero de Morningstar.es,
que publica el NAV de la mayoria de fondos europeos por ISIN.

NOTA: si Morningstar cambia el HTML de sus paginas, habra que ajustar
los patrones regex. Es lo que hay con el scraping.
"""
import json
import logging
import re
from typing import Optional

import httpx

log = logging.getLogger("bot-finanzas.prices")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def looks_like_isin(s: str) -> bool:
    """Un ISIN tiene 12 caracteres alfanumericos y empieza por 2 letras."""
    if not s:
        return False
    s = s.strip().upper()
    if len(s) != 12:
        return False
    return s[:2].isalpha() and s[2:].isalnum()


def fetch_fund_nav(isin: str) -> Optional[float]:
    """
    Devuelve el NAV (precio actual) de un fondo en EUR, buscando por ISIN.
    Devuelve None si no se encuentra o si Morningstar bloquea la peticion.
    """
    isin = (isin or "").strip().upper()
    if not looks_like_isin(isin):
        return None

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
            # Paso 1: buscar por ISIN. La pagina suele redirigir directo al snapshot
            # del fondo si solo hay una coincidencia.
            search_url = (
                f"https://www.morningstar.es/es/funds/SecuritySearchResults.aspx"
                f"?search={isin}&type="
            )
            r = client.get(search_url)
            html = r.text

            # Si no estamos en snapshot, buscar el primer link de resultados.
            if "snapshot.aspx" not in str(r.url):
                m = re.search(
                    r'href="([^"]*?/funds/snapshot/snapshot\.aspx\?id=[^"&]+[^"]*)"',
                    html,
                )
                if not m:
                    log.warning(f"Morningstar: no hay resultados para {isin}")
                    return None
                snapshot_path = m.group(1)
                if snapshot_path.startswith("/"):
                    snapshot_url = "https://www.morningstar.es" + snapshot_path
                elif snapshot_path.startswith("http"):
                    snapshot_url = snapshot_path
                else:
                    snapshot_url = "https://www.morningstar.es/" + snapshot_path
                r = client.get(snapshot_url)
                html = r.text

            return _parse_nav(html)
    except Exception as e:
        log.warning(f"Morningstar fetch failed para {isin}: {e}")
        return None


def _parse_nav(html: str) -> Optional[float]:
    """Extrae el NAV del HTML de la pagina snapshot de Morningstar.es.

    Probamos varios patrones porque la estructura cambia segun el tipo de fondo.
    """
    # Patron 1: bloque "VL" (Valor Liquidativo) tipico
    # <td class="line heading">VL ...</td><td class="line text">EUR&nbsp;22,35</td>
    patterns = [
        r'VL[^<]{0,80}</td>\s*<td[^>]*>\s*(?:EUR|USD|GBP)?\s*&nbsp;\s*([\d.,]+)',
        r'>\s*EUR\s*&nbsp;\s*([\d.,]+)\s*<',
        r'>\s*EUR\s+([\d.,]+)\s*<',
        r'"latestNAV"\s*:\s*"?([\d.,]+)"?',
        r'"price"\s*:\s*"?([\d.,]+)"?',
        r'data-price="([\d.,]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, flags=re.IGNORECASE)
        if m:
            val = _to_float_es(m.group(1))
            if val is not None and val > 0:
                return val
    return None


def _to_float_es(s: str) -> Optional[float]:
    """Convierte '1.234,56' o '22,35' o '22.35' a float."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    # Si tiene punto y coma -> punto = miles, coma = decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
