"""SEC EDGAR XBRL (gratuito, sin API key) para contrastar datos de emisores de EE. UU.

La SEC exige un User-Agent con contacto: define DCFVAL_SEC_UA="Nombre email@dominio".
Sólo rellena huecos y añade avisos si hay discrepancias grandes con Yahoo.
"""
from __future__ import annotations

import os

from . import cache
from .base import CompanyData

UA = os.environ.get("DCFVAL_SEC_UA", "dcfval research dcfval@example.com")


def _get_json(url: str):
    import requests
    r = requests.get(url, timeout=15, headers={"User-Agent": UA})
    r.raise_for_status()
    return r.json()


def _cik(ticker: str) -> str | None:
    table = cache.get("sec:tickers")
    if table is None:
        raw = _get_json("https://www.sec.gov/files/company_tickers.json")
        table = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
        cache.put("sec:tickers", table)
    return table.get(ticker.upper())


def _latest(facts: dict, taxonomy: str, concept: str, unit: str):
    try:
        items = facts["facts"][taxonomy][concept]["units"][unit]
    except KeyError:
        return None
    items = [i for i in items if i.get("form") in ("10-K", "10-Q")]
    if not items:
        return None
    return max(items, key=lambda i: i["end"])["val"]


def enrich(d: CompanyData) -> CompanyData:
    if d.country != "United States" or "." in d.ticker:
        return d
    try:
        cik = _cik(d.ticker)
        if not cik:
            return d
        facts = cache.get(f"sec:facts:{cik}")
        if facts is None:
            facts = _get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
            cache.put(f"sec:facts:{cik}", facts)
    except Exception as e:  # sin red o bloqueado
        d.warnings.append(f"SEC EDGAR no disponible ({type(e).__name__})")
        return d

    d.sources.append("SEC EDGAR XBRL")
    sh = _latest(facts, "dei", "EntityCommonStockSharesOutstanding", "shares")
    if sh:
        if d.shares != d.shares:  # NaN
            d.shares = float(sh)
        elif abs(sh / d.shares - 1) > 0.05:
            d.warnings.append(f"Acciones Yahoo {d.shares:,.0f} vs SEC {sh:,.0f} (>5 % diferencia)")
    eq = _latest(facts, "us-gaap", "StockholdersEquity", "USD")
    if eq and d.book_equity != d.book_equity:
        d.book_equity = float(eq)
    return d
