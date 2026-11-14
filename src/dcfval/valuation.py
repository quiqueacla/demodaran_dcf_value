"""Orquestador: datos -> clasificación -> coste de capital -> modelo -> análisis."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from .config import Assumptions
from .data import yahoo, sec
from .data.base import CompanyData
from .models import fcff, financials
from .models.classify import classify
from .models.discount import CostOfCapital, cost_of_capital


@dataclass
class ValuationResult:
    ticker: str
    name: str
    model_type: str
    currency: str
    price: float
    value_per_share: float
    upside: float
    verdict: str
    data: CompanyData
    coc: CostOfCapital
    assumptions: Assumptions
    model: object                      # FCFFResult | EquityModelResult
    scenarios: dict = field(default_factory=dict)
    sensitivity: pd.DataFrame | None = None
    reverse: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    date: str = field(default_factory=lambda: dt.date.today().isoformat())

    @property
    def buy_below(self) -> float:
        return self.value_per_share * (1 - self.assumptions.margin_of_safety)


def _run_model(d, a, mtype, coc):
    if mtype in ("bank", "insurance"):
        return financials.run(d, a, coc)
    return fcff.run(d, a, coc)


def _verdict(upside: float, mos: float) -> str:
    if upside >= mos / (1 - mos):     # precio <= valor·(1-MoS)
        return "INFRAVALORADA (con margen de seguridad)"
    if upside >= 0:
        return "Ligeramente infravalorada"
    if upside >= -0.15:
        return "Valoración razonable / ligeramente cara"
    return "SOBREVALORADA"


def _scenarios(d, a: Assumptions, mtype, coc):
    out = {}
    if mtype in ("bank", "insurance"):
        base_inp, _ = financials.base_inputs(d, a, coc)
        specs = {
            "bajista": dict(roe=base_inp["roe0"] - 0.02, terminal_roe=base_inp["terminal_roe"] - 0.015, dk=0.01),
            "base": dict(dk=0.0),
            "alcista": dict(roe=base_inp["roe0"] + 0.02, terminal_roe=base_inp["terminal_roe"] + 0.01, dk=-0.005),
        }
    else:
        base_inp, _ = fcff.base_inputs(d, a, coc)
        g0, m = base_inp["g0"], base_inp["target_margin"]
        specs = {
            "bajista": dict(revenue_growth=g0 - max(0.03, abs(g0) * 0.5), target_margin=m * 0.85, dk=0.01),
            "base": dict(dk=0.0),
            "alcista": dict(revenue_growth=g0 + max(0.02, abs(g0) * 0.3), target_margin=m * 1.10, dk=-0.005),
        }
    for name, s in specs.items():
        dk = s.pop("dk")
        try:
            r = _run_model(d, a.merged(s), mtype, coc.shifted(dk))
            out[name] = dict(value_per_share=r.value_per_share, discount_rate_shift=dk, **s)
        except Exception as e:
            out[name] = dict(error=str(e))
    return out


def _sensitivity(d, a: Assumptions, mtype, coc):
    step = a.sensitivity_steps
    shifts = [-2 * step, -step, 0.0, step, 2 * step]
    g0 = coc.terminal_growth
    gs = [g0 + s for s in shifts]
    rows = {}
    rate_name = "Ke" if mtype in ("bank", "insurance") else "WACC"
    base_rate = coc.ke if mtype in ("bank", "insurance") else coc.wacc
    for dk in shifts:
        row = {}
        for g in gs:
            c = coc.shifted(dk)
            c.terminal_growth = g
            try:
                row[f"g={g:.2%}"] = _run_model(d, a, mtype, c).value_per_share
            except Exception:
                row[f"g={g:.2%}"] = float("nan")
        rows[f"{rate_name}={base_rate + dk:.2%}"] = row
    return pd.DataFrame(rows).T


def _bisect(f, lo, hi, target, iters=60):
    flo, fhi = f(lo) - target, f(hi) - target
    if flo * fhi > 0:
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        fm = f(mid) - target
        if abs(fm) < 1e-6 * max(1, abs(target)):
            return mid
        if flo * fm <= 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def _reverse(d, a: Assumptions, mtype, coc):
    """DCF inverso: qué supuesto descuenta el precio actual."""
    price = d.price
    out = {}
    try:
        if mtype in ("bank", "insurance"):
            def f(x):
                return financials.run(d, a.merged({"roe": x, "terminal_roe": x}), coc).components["excess_return"]
            x = _bisect(f, coc.terminal_growth + 0.001, 0.45, price)
            out["implied_sustained_roe"] = x
        else:
            def f(x):
                return fcff.run(d, a.merged({"revenue_growth": x}), coc).value_per_share
            out["implied_revenue_growth"] = _bisect(f, -0.10, 0.60, price)

            def fr(x):
                return fcff.run(d, a, coc.shifted(x - coc.wacc)).value_per_share
            out["implied_wacc"] = _bisect(fr, coc.terminal_growth + 0.005, 0.30, price)
    except Exception as e:
        out["error"] = str(e)
    return out


def value_company(ticker: str, assumptions: Assumptions | None = None,
                  overrides: dict | None = None, model: str | None = None,
                  data: CompanyData | None = None, use_sec: bool = True,
                  extras: bool = True) -> ValuationResult:
    a = (assumptions or Assumptions()).merged(overrides)
    d = data or yahoo.fetch(ticker)
    if use_sec and data is None:
        d = sec.enrich(d)
    mtype = classify(d, model)
    coc = cost_of_capital(d, a, mtype)
    res = _run_model(d, a, mtype, coc)
    vps = res.value_per_share
    upside = vps / d.price - 1
    vr = ValuationResult(ticker=d.ticker, name=d.name, model_type=mtype, currency=d.currency,
                         price=d.price, value_per_share=vps, upside=upside,
                         verdict=_verdict(upside, a.margin_of_safety), data=d, coc=coc,
                         assumptions=a, model=res,
                         warnings=list(d.warnings) + list(res.warnings))
    if extras:
        vr.scenarios = _scenarios(d, a, mtype, coc)
        vr.sensitivity = _sensitivity(d, a, mtype, coc)
        vr.reverse = _reverse(d, a, mtype, coc)
    return vr
