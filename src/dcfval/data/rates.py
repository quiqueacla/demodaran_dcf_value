"""Tipo libre de riesgo por divisa desde fuentes gratuitas.

USD : Yahoo ^TNX (Treasury 10a)  -> FRED DGS10 (CSV sin API key)
EUR : BCE, curva AAA zona euro 10a (data-api.ecb.europa.eu, sin API key)
otras: tabla de respaldo en config.RF_FALLBACK
"""
from __future__ import annotations

import csv
import io

from .. import config
from . import cache

TIMEOUT = 10


def _http_get(url: str) -> str:
    import requests
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "dcfval/1.0"})
    r.raise_for_status()
    return r.text


def _us_yahoo() -> float:
    import yfinance as yf
    v = float(yf.Ticker("^TNX").history(period="5d")["Close"].dropna().iloc[-1])
    return v / 100.0


def _us_fred() -> float:
    txt = _http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10")
    rows = [r for r in csv.reader(io.StringIO(txt))][1:]
    vals = [float(r[1]) for r in rows if len(r) > 1 and r[1] not in (".", "")]
    return vals[-1] / 100.0


def _eur_ecb() -> float:
    url = ("https://data-api.ecb.europa.eu/service/data/YC/"
           "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y?lastNObservations=1&format=csvdata")
    txt = _http_get(url)
    rdr = csv.DictReader(io.StringIO(txt))
    rows = list(rdr)
    return float(rows[-1]["OBS_VALUE"]) / 100.0


SOURCES = {
    "USD": [("Yahoo ^TNX", _us_yahoo), ("FRED DGS10", _us_fred)],
    "EUR": [("BCE curva AAA 10a", _eur_ecb)],
}


def risk_free(currency: str) -> tuple[float, str]:
    key = f"rf:{currency}"
    hit = cache.get(key)
    if hit:
        return hit
    for name, fn in SOURCES.get(currency, []):
        try:
            v = fn()
            if 0.0 <= v < 0.25:
                cache.put(key, (v, name))
                return v, name
        except Exception:
            continue
    v = config.RF_FALLBACK.get(currency, config.RF_FALLBACK["USD"])
    return v, f"tabla de respaldo ({currency})"
