"""Estructura normalizada de datos de una compañía (independiente de la fuente)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class CompanyData:
    ticker: str
    name: str = ""
    sector: str = ""
    industry: str = ""
    country: str = ""
    currency: str = "USD"            # divisa de cotización
    financial_currency: str = "USD"  # divisa de los estados financieros
    fx_to_price: float = 1.0         # 1 unidad financiera -> divisa de cotización
    price: float = float("nan")
    shares: float = float("nan")     # acciones diluidas en circulación
    market_cap: float = float("nan")
    beta_regression: Optional[float] = None

    # Cuenta de resultados (TTM o último año), en divisa financiera
    revenue: float = float("nan")
    ebit: float = float("nan")
    interest_expense: float = float("nan")
    pretax_income: float = float("nan")
    tax_provision: float = float("nan")
    net_income: float = float("nan")
    depreciation: float = float("nan")

    # Flujo de caja
    capex: float = float("nan")          # positivo = inversión
    delta_wc: float = float("nan")       # positivo = consumo de caja
    dividends_paid: float = 0.0          # positivo
    buybacks: float = 0.0                # positivo (neto de emisiones)
    fcf_reported: float = float("nan")

    # Balance
    total_debt: float = float("nan")     # incl. arrendamientos si la fuente los da
    cash: float = float("nan")           # caja + inversiones a corto
    minority_interest: float = 0.0
    equity_investments: float = 0.0      # participadas no operativas
    book_equity: float = float("nan")    # patrimonio atribuido a la dominante
    book_equity_prev: float = float("nan")
    tangible_book: float = float("nan")
    total_assets: float = float("nan")

    # Históricos anuales (antiguo -> reciente)
    revenue_hist: list = field(default_factory=list)
    ebit_hist: list = field(default_factory=list)
    net_income_hist: list = field(default_factory=list)
    equity_hist: list = field(default_factory=list)
    invested_capital_hist: list = field(default_factory=list)
    # Tabla anual con fecha: {"2023-12-31": {"revenue": .., "ebit": .., ...}, ...} (antiguo -> reciente)
    annual_hist: dict = field(default_factory=dict)

    # Consenso de analistas
    analyst_revenue_growth: Optional[float] = None   # próximo año fiscal
    analyst_eps_growth_lt: Optional[float] = None    # crecimiento LP (5 años)

    dividend_per_share: float = 0.0
    sources: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def invested_capital(self) -> float:
        return _nz(self.book_equity) + _nz(self.total_debt) - _nz(self.cash) + _nz(self.minority_interest)

    @property
    def market_cap_fin(self) -> float:
        """Capitalización en divisa financiera."""
        return self.price * self.shares / self.fx_to_price

    def to_dict(self) -> dict:
        return asdict(self)


def _nz(x, default=0.0):
    try:
        if x is None or x != x:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


nz = _nz
