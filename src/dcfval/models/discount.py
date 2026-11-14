"""Coste de los recursos propios (CAPM + prima país) y WACC."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, asdict

from .. import config
from ..config import Assumptions
from ..data import damodaran, rates
from ..data.base import CompanyData, nz


@dataclass
class CostOfCapital:
    rf: float
    erp: float
    crp: float
    beta: float
    beta_detail: dict
    ke: float
    kd_pre: float
    rating: str
    coverage: float
    tax_marginal: float
    kd_after: float
    we: float
    wd: float
    wacc: float
    ke_terminal: float
    wacc_terminal: float
    terminal_growth: float
    sources: dict = field(default_factory=dict)

    def shifted(self, dx: float) -> "CostOfCapital":
        c = copy.copy(self)
        c.ke += dx
        c.wacc += dx
        c.ke_terminal += dx
        c.wacc_terminal += dx
        return c

    def to_dict(self):
        return asdict(self)


def synthetic_rating(coverage: float) -> tuple[str, float]:
    for floor, rating, spread in config.SYNTHETIC_RATINGS:
        if coverage >= floor:
            return rating, spread
    return "D", config.SYNTHETIC_RATINGS[-1][2]


def _beta(d: CompanyData, a: Assumptions, model_type: str, tax: float) -> tuple[float, dict]:
    if a.beta is not None:
        return float(a.beta), {"method": "manual", "beta": a.beta}
    det: dict = {}
    reg = d.beta_regression
    if reg is not None and reg == reg and reg > 0:
        det["regression_raw"] = reg
        det["regression_blume"] = 0.67 * reg + 0.33
    if model_type in ("bank", "insurance"):
        # Beta de fondos propios de referencia del sector (no se desapalanca).
        det["bottom_up"] = 1.05 if model_type == "bank" else 0.95
    else:
        bu = config.SECTOR_UNLEVERED_BETA.get(d.sector, config.DEFAULT_UNLEVERED_BETA)
        mcap = d.market_cap_fin
        de = nz(d.total_debt) / mcap if mcap and mcap > 0 else 0.0
        det["unlevered_sector"] = bu
        det["debt_to_equity"] = de
        det["bottom_up"] = bu * (1 + (1 - tax) * de)
    method = a.beta_method
    if method == "regression" and "regression_blume" in det:
        b = det["regression_blume"]
    elif method == "bottom_up" or "regression_blume" not in det:
        b = det["bottom_up"]
    else:
        b = 0.5 * (det["regression_blume"] + det["bottom_up"])
    b = min(max(b, 0.4), 2.5)
    det["method"] = method
    det["beta"] = b
    return b, det


def cost_of_capital(d: CompanyData, a: Assumptions, model_type: str) -> CostOfCapital:
    sources = {}
    if a.rf is not None:
        rf, sources["rf"] = float(a.rf), "manual"
    else:
        rf, sources["rf"] = rates.risk_free(d.financial_currency)
    if a.crp is not None:
        crp, sources["crp"] = float(a.crp), "manual"
    else:
        crp, sources["crp"] = damodaran.country_risk_premium(d.country)
    crp *= a.crp_lambda
    erp = a.erp
    tax_m = config.MARGINAL_TAX.get(d.country, config.DEFAULT_TAX)

    beta, bdet = _beta(d, a, model_type, tax_m)
    ke = rf + beta * erp + crp
    # En crecimiento estable la beta converge hacia el mercado: [0,8; 1,2] (Damodaran)
    beta_term = min(max(beta, a.terminal_beta_min), a.terminal_beta_max)
    bdet["beta_terminal"] = beta_term

    g = a.terminal_growth if a.terminal_growth is not None else min(rf, a.terminal_growth_cap)

    if model_type in ("bank", "insurance"):
        # Para financieras sólo importa Ke (la deuda es operativa).
        ke_term = rf + beta_term * erp + crp
        return CostOfCapital(rf, erp, crp, beta, bdet, ke, float("nan"), "n/a", float("nan"),
                             tax_m, float("nan"), 1.0, 0.0, ke, ke_term, ke_term, g, sources)

    ebit, intexp = nz(d.ebit), nz(d.interest_expense)
    coverage = ebit / intexp if intexp > 0 else 100.0
    rating, spread = synthetic_rating(coverage)
    kd_pre = rf + spread
    kd_after = kd_pre * (1 - tax_m)

    e = d.market_cap_fin
    debt = max(nz(d.total_debt), 0.0)
    we = e / (e + debt) if e + debt > 0 else 1.0
    wd = 1 - we
    wacc = we * ke + wd * kd_after

    # Terminal: beta acotada a [0,8; 1,2], misma estructura de capital
    ke_term = rf + beta_term * erp + crp
    wacc_term = we * ke_term + wd * kd_after
    return CostOfCapital(rf, erp, crp, beta, bdet, ke, kd_pre, rating, coverage, tax_m,
                         kd_after, we, wd, wacc, ke_term, wacc_term, g, sources)


def path(start: float, end: float, years: int, hold: int) -> list[float]:
    """Mantiene `start` durante `hold` años y converge linealmente a `end` en `years`."""
    out = []
    for t in range(1, years + 1):
        if t <= hold:
            out.append(start)
        else:
            frac = (t - hold) / max(years - hold, 1)
            out.append(start + (end - start) * frac)
    return out
