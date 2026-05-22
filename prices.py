"""Obtiene NAVs de fondos indexados y ETFs por ISIN.

Estrategia: probar varias fuentes en cascada hasta que una devuelva un precio.

Fuentes (orden):
  1. FT.com (Financial Times) — tearsheet publico con ISIN, robusto.
  2. Morningstar.es — autocomplete + snapshot por MS_ID.
  3. Yahoo Finance — ultimo recurso para ETFs con sufijo de mercado.

Si ninguna funciona, devuelve None y el usuario lo pone con /precio a mano.
"""
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
    "Referer": "https://www.google.com/",
}

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def looks_like_isin(s: str) -> bool:
    """ISIN: 12 caracteres, empieza con 2 letras."""
    if not s:
        return False
    s = s.strip().upper()
    if len(s) != 12:
        return False
    return s[:2].isalpha() and s[2:].isalnum()


def fetch_fund_nav(isin: str) -> Optional[float]:
    """Devuelve el precio actual en EUR de un fondo/ETF dado su ISIN.

    Prueba varias fuentes en orden. Devuelve None si todas fallan.
    """
    isin = (isin or "").strip().upper()
    if not looks_like_isin(isin):
        return None

    for fn, name in (
        (_fetch_ft, "FT"),
        (_fetch_morningstar, "Morningstar"),
        (_fetch_yahoo, "Yahoo"),
    ):
        try:
            nav = fn(isin)
        except Exception as e:
            log.warning(f"{name} failed for {isin}: {e}")
            continue
        if nav is not None and nav > 0:
            log.info(f"{name} -> {isin} = {nav}")
            return nav
    log.warning(f"Ninguna fuente encontro precio para {isin}")
    return None


# ─────────────────────────────────────────────────────────────────
# Financial Times
# ─────────────────────────────────────────────────────────────────
def _fetch_ft(isin: str) -> Optional[float]:
    """FT.com tearsheet. Funciona para fondos UCITS y ETFs.

    URLs probadas:
      - https://markets.ft.com/data/funds/tearsheet/summary?s={ISIN}:EUR
      - https://markets.ft.com/data/etfs/tearsheet/summary?s={ISIN}:EUR
    """
    candidatos = [
        f"https://markets.ft.com/data/funds/tearsheet/summary?s={isin}:EUR",
        f"https://markets.ft.com/data/etfs/tearsheet/summary?s={isin}:EUR",
        f"https://markets.ft.com/data/funds/tearsheet/summary?s={isin}",
        f"https://markets.ft.com/data/etfs/tearsheet/summary?s={isin}",
    ]
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as c:
        for url in candidatos:
            r = c.get(url)
            if r.status_code != 200:
                continue
            html = r.text
            # Heuristica: si la pagina responde "no resultados", saltar
            if "could not find" in html.lower() or "no results" in html.lower():
                continue
            # FT pone el precio destacado:
            #   <span class="mod-ui-data-list__value">22.35</span>
            patterns = [
                r'class="mod-ui-data-list__value"[^>]*>\s*([\d,\.]+)\s*<',
                r'class="mod-tearsheet-overview__quote__value"[^>]*>\s*([\d,\.]+)',
                r'"lastPrice"\s*:\s*"?([\d,\.]+)"?',
                r'data-price="([\d,\.]+)"',
            ]
            for pat in patterns:
                m = re.search(pat, html)
                if m:
                    val = _to_float(m.group(1))
                    if val and val > 0:
                        return val
    return None


# ─────────────────────────────────────────────────────────────────
# Morningstar.es
# ─────────────────────────────────────────────────────────────────
def _fetch_morningstar(isin: str) -> Optional[float]:
    """Morningstar.es via endpoint de autocomplete + snapshot."""
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as c:
        # Endpoint interno de autocomplete que devuelve HTML con el MS_ID
        ac_url = (
            f"https://www.morningstar.es/es/util/SecuritySearch.ashx"
            f"?source=&q={isin}&limit=5"
        )
        r = c.get(ac_url)
        if r.status_code != 200:
            return None
        text = r.text
        m = re.search(r'snapshot\.aspx\?id=([A-Z0-9]+)', text)
        if not m:
            # Probar como enlace HTML normal en busqueda
            search_url = (
                f"https://www.morningstar.es/es/funds/SecuritySearchResults.aspx"
                f"?search={isin}"
            )
            r2 = c.get(search_url)
            m = re.search(r'snapshot\.aspx\?id=([A-Z0-9]+)', r2.text)
            if not m:
                return None
        ms_id = m.group(1)

        snap_url = f"https://www.morningstar.es/es/funds/snapshot/snapshot.aspx?id={ms_id}"
        r3 = c.get(snap_url)
        if r3.status_code != 200:
            return None
        html = r3.text
        patterns = [
            r'VL[^<]{0,80}</td>\s*<td[^>]*>\s*(?:EUR|USD|GBP)?\s*&nbsp;?\s*([\d,\.]+)',
            r'>\s*EUR\s*&nbsp;?\s*([\d,\.]+)\s*<',
            r'data-price="([\d,\.]+)"',
            r'"latestNAV"\s*:\s*"?([\d,\.]+)"?',
        ]
        for pat in patterns:
            m = re.search(pat, html, flags=re.IGNORECASE)
            if m:
                val = _to_float(m.group(1))
                if val and val > 0:
                    return val
    return None


# ─────────────────────────────────────────────────────────────────
# Yahoo Finance (fallback para ETFs)
# ─────────────────────────────────────────────────────────────────
def _fetch_yahoo(isin: str) -> Optional[float]:
    """Yahoo Finance: a veces tiene ETFs europeos con sufijo de mercado.
    Probamos con ISIN puro y con sufijos comunes (.AS, .L, .DE, .MI)."""
    sufijos = ["", ".AS", ".L", ".DE", ".MI", ".PA"]
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as c:
        for suf in sufijos:
            sym = isin + suf
            url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={sym}"
            r = c.get(url)
            if r.status_code != 200:
                continue
            try:
                data = r.json()
                results = data.get("quoteResponse", {}).get("result", [])
                if results and "regularMarketPrice" in results[0]:
                    val = float(results[0]["regularMarketPrice"])
                    if val > 0:
                        return val
            except Exception:
                continue
    return None


def _to_float(s: str) -> Optional[float]:
    """Convierte '1.234,56', '22,35', '22.35' o '1,234.56' a float."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if "," in s and "." in s:
        # Si el ultimo separador es coma -> formato europeo (punto miles)
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            # Formato anglosajon (coma miles)
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
