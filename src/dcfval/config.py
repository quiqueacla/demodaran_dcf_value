"""Supuestos por defecto y tablas de referencia.

Todas las tablas embebidas son *fallbacks*. Si hay red, el modelo intenta
descargar los datos vivos (Damodaran, ECB, FRED). Los valores embebidos
proceden de las publicaciones de A. Damodaran (NYU Stern):
  - ERP madura: 4,17 % (actualización julio 2026)
  - Primas país (CRP): tabla de enero 2026 (ctryprem.html)
  - Spreads por rating sintético: tabla de Damodaran para grandes empresas
Revísalos periódicamente o sobrescríbelos con un YAML (ver config.example.yaml).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Mercado
# --------------------------------------------------------------------------
MATURE_ERP = 0.0417  # Damodaran, julio 2026

# Tipo libre de riesgo de respaldo por divisa (10 años, soberano AAA/local).
# Se usa sólo si falla la descarga en vivo. Valores aprox. nov-2026.
RF_FALLBACK = {
    "USD": 0.0450,
    "EUR": 0.0325,  # Bund 10a ~3,25 % (9-nov-2026)
    "GBP": 0.0450,
    "CHF": 0.0100,
    "JPY": 0.0150,
    "SEK": 0.0280,
    "NOK": 0.0400,
    "DKK": 0.0300,
    "CAD": 0.0350,
    "AUD": 0.0450,
}

# Prima de riesgo país adicional (CRP) -- Damodaran, enero 2026 (aprox.).
COUNTRY_RISK_PREMIUM = {
    "United States": 0.0028,
    "Germany": 0.0, "Netherlands": 0.0, "Denmark": 0.0, "Luxembourg": 0.0,
    "Sweden": 0.0, "Norway": 0.0, "Switzerland": 0.0, "Australia": 0.0,
    "Canada": 0.0, "Singapore": 0.0, "New Zealand": 0.0,
    "Austria": 0.0036, "Finland": 0.0036,
    "France": 0.0078, "Belgium": 0.0078, "Ireland": 0.0078,
    "United Kingdom": 0.0078, "Czech Republic": 0.0078,
    "Japan": 0.0091, "China": 0.0091, "Hong Kong": 0.0078, "Taiwan": 0.0078,
    "South Korea": 0.0078, "Estonia": 0.0091,
    "Poland": 0.0110, "Lithuania": 0.0110, "Malta": 0.0110, "Chile": 0.0110,
    "Spain": 0.0155, "Portugal": 0.0155, "Croatia": 0.0155, "Slovenia": 0.0155,
    "Slovakia": 0.0155, "Cyprus": 0.0155, "Latvia": 0.0155,
    "Italy": 0.0246, "Hungary": 0.0246, "Mexico": 0.0246, "Bulgaria": 0.0207,
    "Greece": 0.0285, "Romania": 0.0285, "India": 0.0285, "Colombia": 0.0285,
    "Brazil": 0.0350, "South Africa": 0.0400, "Turkey": 0.0580,
    "Argentina": 0.1200,
}
DEFAULT_CRP = 0.0150  # país no encontrado

# Tipo impositivo marginal (para el periodo terminal).
MARGINAL_TAX = {
    "United States": 0.25, "Spain": 0.25, "Germany": 0.30, "France": 0.25,
    "Italy": 0.279, "Netherlands": 0.258, "Portugal": 0.31, "Ireland": 0.125,
    "United Kingdom": 0.25, "Switzerland": 0.197, "Belgium": 0.25,
    "Austria": 0.23, "Sweden": 0.206, "Norway": 0.22, "Denmark": 0.22,
    "Finland": 0.20, "Luxembourg": 0.249, "Japan": 0.306, "Canada": 0.265,
    "Brazil": 0.34, "Mexico": 0.30, "China": 0.25, "Greece": 0.22,
}
DEFAULT_TAX = 0.25

# Rating sintético por cobertura de intereses (EBIT / gastos financieros),
# tabla Damodaran para grandes empresas no financieras.
# (cobertura mínima, rating, spread sobre Rf)
SYNTHETIC_RATINGS = [
    (8.50, "AAA", 0.0040),
    (6.50, "AA", 0.0055),
    (5.50, "A+", 0.0070),
    (4.25, "A", 0.0078),
    (3.00, "A-", 0.0089),
    (2.50, "BBB", 0.0111),
    (2.25, "BB+", 0.0138),
    (2.00, "BB", 0.0184),
    (1.75, "B+", 0.0275),
    (1.50, "B", 0.0321),
    (1.25, "B-", 0.0500),
    (0.80, "CCC", 0.0800),
    (0.65, "CC", 0.1000),
    (0.20, "C", 0.1200),
    (-1e9, "D", 0.1500),
]
# Probabilidad de quiebra aproximada asociada al rating (acumulada 10 años).
DISTRESS_PROB = {"B-": 0.10, "CCC": 0.25, "CC": 0.40, "C": 0.55, "D": 0.70}

# Betas desapalancadas aproximadas por sector Yahoo (orden de magnitud de
# los datos globales de Damodaran). Se usan para la beta "bottom-up".
# Industrias cíclicas (Yahoo): el margen se normaliza a la media del ciclo y
# converge en `cyclical_margin_years` años en lugar de en todo el horizonte.
CYCLICAL_INDUSTRIES = (
    "Airlines", "Oil & Gas", "Steel", "Aluminum", "Copper", "Other Industrial Metals",
    "Other Precious Metals", "Gold", "Silver", "Coking Coal", "Thermal Coal", "Uranium",
    "Chemicals", "Specialty Chemicals", "Auto Manufacturers", "Auto Parts",
    "Building Materials", "Marine Shipping", "Semiconductor", "Agricultural Inputs",
    "Paper & Paper Products", "Lumber & Wood Production", "Farm & Heavy Construction",
    "Trucking", "Residential Construction", "Travel Services", "Resorts & Casinos",
)

SECTOR_UNLEVERED_BETA = {
    "Technology": 1.15,
    "Communication Services": 0.85,
    "Consumer Cyclical": 0.95,
    "Consumer Defensive": 0.60,
    "Healthcare": 0.90,
    "Industrials": 0.85,
    "Basic Materials": 0.90,
    "Energy": 0.85,
    "Utilities": 0.45,
    "Real Estate": 0.60,
    "Financial Services": 0.80,
}
DEFAULT_UNLEVERED_BETA = 0.90


# --------------------------------------------------------------------------
# Supuestos del modelo (sobrescribibles por YAML / CLI / por ticker)
# --------------------------------------------------------------------------
@dataclass
class Assumptions:
    # Generales
    years: int = 10                 # horizonte explícito
    high_growth_years: int = 5      # años a crecimiento inicial antes de converger
    erp: float = MATURE_ERP
    rf: float | None = None         # None = automático por divisa
    crp: float | None = None        # None = por país de domicilio
    crp_lambda: float = 1.0         # exposición al riesgo país
    terminal_growth: float | None = None  # None = min(rf, terminal_growth_cap)
    terminal_growth_cap: float = 0.025
    beta: float | None = None       # None = automático
    beta_method: str = "blend"      # regression | bottom_up | blend
    terminal_beta_min: float = 0.8  # beta en estable acotada a [min, max]
    terminal_beta_max: float = 1.2
    mid_year: bool = True           # convención de mitad de año

    # No financieras (FCFF)
    revenue_growth: float | None = None    # crecimiento inicial (None = auto)
    target_margin: float | None = None     # margen EBIT objetivo (None = auto)
    sales_to_capital: float | None = None  # (None = auto)
    terminal_roic: float | None = None     # (None = WACC + 50 % del exceso actual, máx +5 pp)
    failure_prob: float | None = None      # (None = por rating sintético)
    distress_recovery: float = 0.5         # % del valor recuperado en quiebra
    tax_rate: float | None = None          # efectivo inicial (None = auto)
    cyclical: bool | None = None           # None = según industria
    cyclical_margin_years: int = 3         # años para normalizar margen en cíclicas

    # Financieras (bancos / aseguradoras)
    roe: float | None = None               # ROE sostenible inicial (None = auto)
    terminal_roe: float | None = None      # (None = Ke + 50 % del exceso, máx +4 pp)
    payout: float | None = None            # payout total inicial (None = auto)
    include_buybacks: bool = True          # contar recompras como retorno al accionista
    bank_weights: dict = field(default_factory=lambda: {
        "excess_return": 0.5, "ddm": 0.3, "justified_pbv": 0.2})

    # Análisis
    margin_of_safety: float = 0.25
    sensitivity_steps: float = 0.005

    def merged(self, overrides: dict | None) -> "Assumptions":
        if not overrides:
            return self
        new = copy.deepcopy(self)
        for k, v in overrides.items():
            if hasattr(new, k):
                setattr(new, k, v)
        return new

    def to_dict(self) -> dict:
        return asdict(self)


def load_config(path: str | Path | None) -> tuple[Assumptions, dict[str, dict]]:
    """Carga YAML/JSON con claves `defaults:` y `tickers: {TICKER: {...}}`."""
    base = Assumptions()
    if not path:
        return base, {}
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml  # dependencia opcional
        data: dict[str, Any] = yaml.safe_load(text) or {}
    else:
        import json
        data = json.loads(text)
    base = base.merged(data.get("defaults"))
    per_ticker = {k.upper(): v for k, v in (data.get("tickers") or {}).items()}
    return base, per_ticker
