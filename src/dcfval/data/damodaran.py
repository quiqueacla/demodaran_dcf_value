"""Primas de riesgo país de A. Damodaran (ctryprem.xlsx), con respaldo embebido."""
from __future__ import annotations

import io

from .. import config
from . import cache

URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctryprem.xlsx"


def _download() -> dict[str, float]:
    import pandas as pd
    import requests
    r = requests.get(URL, timeout=20, headers={"User-Agent": "dcfval/1.0"})
    r.raise_for_status()
    book = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None)
    for _, df in book.items():
        # Buscar fila de cabecera con 'Country' y 'Country Risk Premium'
        for i in range(min(len(df), 30)):
            row = [str(x).strip() for x in df.iloc[i].tolist()]
            if "Country" in row and any("Country Risk Premium" in x for x in row):
                ci = row.index("Country")
                pi = next(j for j, x in enumerate(row) if "Country Risk Premium" in x)
                out = {}
                for _, r2 in df.iloc[i + 1:].iterrows():
                    c, p = r2.iloc[ci], r2.iloc[pi]
                    try:
                        out[str(c).strip()] = float(p)
                    except (TypeError, ValueError):
                        continue
                if len(out) > 50:
                    return out
    raise ValueError("Formato de ctryprem.xlsx no reconocido")


def country_risk_premium(country: str) -> tuple[float, str]:
    table = cache.get("damodaran:crp")
    src = "Damodaran ctryprem.xlsx (descarga)"
    if table is None:
        try:
            table = _download()
            cache.put("damodaran:crp", table)
        except Exception:
            table = None
    if table and country in table:
        return table[country], src
    if country in config.COUNTRY_RISK_PREMIUM:
        return config.COUNTRY_RISK_PREMIUM[country], "Damodaran ene-2026 (tabla embebida)"
    return config.DEFAULT_CRP, f"por defecto (país '{country}' no encontrado)"
