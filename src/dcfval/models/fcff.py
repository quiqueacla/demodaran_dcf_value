"""Modelo FCFF a dos etapas (Damodaran) para empresas no financieras.

Ingresos  -> crecen a g0 durante `high_growth_years` y convergen a g terminal.
Margen    -> converge del actual al objetivo.
Impuestos -> convergen del efectivo al marginal.
Reinversión = ΔIngresos / (Ventas / Capital invertido)
FCFF = EBIT·(1-t) - Reinversión
Valor terminal: FCFF_{N+1} = NOPAT_{N+1}·(1 - g/ROIC_terminal) / (WACC_term - g)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import statistics

import pandas as pd

from .. import config
from ..config import Assumptions
from ..data.base import CompanyData, nz
from .discount import CostOfCapital, path


@dataclass
class FCFFResult:
    value_per_share: float
    equity_value: float
    operating_value: float
    pv_fcff: float
    pv_terminal: float
    terminal_share: float
    inputs: dict
    projection: pd.DataFrame
    warnings: list = field(default_factory=list)


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def base_inputs(d: CompanyData, a: Assumptions, coc: CostOfCapital) -> tuple[dict, list]:
    w: list[str] = []
    R0 = nz(d.revenue)
    if R0 <= 0:
        raise ValueError("Ingresos no disponibles o nulos: el modelo FCFF no es aplicable")

    margin0 = nz(d.ebit) / R0
    cyclical = a.cyclical if a.cyclical is not None else any(
        (d.industry or "").startswith(x) for x in config.CYCLICAL_INDUSTRIES)
    n_hist = 5 if cyclical else 3
    hist_m = [e / r for e, r in zip(d.ebit_hist[-n_hist:], d.revenue_hist[-n_hist:]) if r]
    avg_m = statistics.mean(hist_m) if hist_m else margin0
    if abs(margin0 - avg_m) > 0.05:
        w.append(f"Margen EBIT TTM ({margin0:.1%}) muy distinto de la media histórica "
                 f"({avg_m:.1%}): posible pico/valle o dato anómalo de Yahoo")
    if cyclical:
        w.append(f"Industria cíclica ({d.industry}): margen normalizado a la media de "
                 f"{len(hist_m) + 1} periodos; revisar target_margin con un ciclo completo")
    if margin0 > 0.80:
        w.append(f"Margen EBIT {margin0:.0%} no plausible (Yahoo incluye otros ingresos/plusvalías): "
                 "objetivo limitado al 60 %")
    if a.target_margin is not None:
        target_m = a.target_margin
    elif margin0 > 0.80:
        target_m = min(avg_m, 0.60)
    elif cyclical:
        target_m = statistics.mean(hist_m + [margin0])
    else:
        target_m = 0.5 * (margin0 + avg_m)
        if target_m <= 0:
            target_m = 0.05
            w.append("Margen EBIT actual/histórico negativo: se asume objetivo 5 %. "
                     "Recomendado fijar --set target_margin=...")

    # Crecimiento inicial
    if a.revenue_growth is not None:
        g0, g_src = a.revenue_growth, "manual"
    elif d.analyst_revenue_growth is not None:
        g0, g_src = d.analyst_revenue_growth, "consenso analistas (Yahoo)"
    elif len(d.revenue_hist) >= 3 and d.revenue_hist[0] > 0:
        n = len(d.revenue_hist) - 1
        g0, g_src = (d.revenue_hist[-1] / d.revenue_hist[0]) ** (1 / n) - 1, f"CAGR {n} años"
    else:
        g0, g_src = coc.terminal_growth, "crecimiento terminal (sin datos)"
    g0 = _clip(g0, -0.10, 0.30)

    # Impuestos
    tax_m = coc.tax_marginal
    if a.tax_rate is not None:
        tax0 = a.tax_rate
    else:
        pt, tp = nz(d.pretax_income), nz(d.tax_provision)
        tax0 = tp / pt if pt > 0 else tax_m
        tax0 = _clip(tax0, 0.0, 0.40)

    # Capital invertido y ventas/capital
    ic0 = d.invested_capital
    if a.sales_to_capital is not None:
        s2c, s2c_src = a.sales_to_capital, "manual"
    else:
        cands = []
        if ic0 > 0:
            cands.append(R0 / ic0)
        ich, rh = d.invested_capital_hist, d.revenue_hist
        if len(ich) >= 2 and len(rh) >= 2:
            n = min(len(ich), len(rh))
            dic, dr = ich[-1] - ich[-n], rh[-1] - rh[-n]
            if dic > 0 and dr > 0:
                cands.append(dr / dic)
        if cands:
            s2c, s2c_src = statistics.median(cands), "histórico (actual y marginal)"
        else:
            s2c, s2c_src = 2.0, "por defecto"
            w.append("Capital invertido no positivo: ventas/capital = 2,0 por defecto")
        s2c = _clip(s2c, 0.3, 6.0)

    roic0 = nz(d.ebit) * (1 - tax0) / ic0 if ic0 > 0 else float("nan")
    if a.terminal_roic is not None:
        roic_t = a.terminal_roic
    else:
        excess = (roic0 - coc.wacc_terminal) if roic0 == roic0 else 0.0
        roic_t = coc.wacc_terminal + _clip(0.5 * excess, 0.0, 0.05)

    if a.failure_prob is not None:
        p_fail = a.failure_prob
    else:
        p_fail = config.DISTRESS_PROB.get(coc.rating, 0.0)

    return dict(R0=R0, margin0=margin0, margin_hist_avg=avg_m, target_margin=target_m,
                g0=g0, g0_source=g_src, tax0=tax0, tax_marginal=tax_m, ic0=ic0,
                sales_to_capital=s2c, s2c_source=s2c_src, roic0=roic0,
                terminal_roic=roic_t, failure_prob=p_fail, cyclical=cyclical), w


def run(d: CompanyData, a: Assumptions, coc: CostOfCapital) -> FCFFResult:
    inp, warns = base_inputs(d, a, coc)
    N, H = a.years, a.high_growth_years
    g = coc.terminal_growth

    growth = path(inp["g0"], g, N, H)
    if inp["cyclical"]:
        k = max(1, min(a.cyclical_margin_years, N))
        margin = path(inp["margin0"], inp["target_margin"], k, 0) + [inp["target_margin"]] * (N - k)
    else:
        margin = path(inp["margin0"], inp["target_margin"], N, 0)
    tax = path(inp["tax0"], inp["tax_marginal"], N, H)
    wacc = path(coc.wacc, coc.wacc_terminal, N, H)

    rows, R, ic, cum = [], inp["R0"], inp["ic0"], 1.0
    pv_sum = 0.0
    for t in range(N):
        R_new = R * (1 + growth[t])
        ebit = R_new * margin[t]
        nopat = ebit * (1 - tax[t])
        reinv = (R_new - R) / inp["sales_to_capital"]
        fcff = nopat - reinv
        cum *= (1 + wacc[t])
        df = 1 / cum
        if a.mid_year:
            df *= (1 + wacc[t]) ** 0.5
        pv = fcff * df
        pv_sum += pv
        ic += reinv
        rows.append(dict(year=t + 1, growth=growth[t], revenue=R_new, ebit_margin=margin[t],
                         ebit=ebit, tax_rate=tax[t], nopat=nopat, reinvestment=reinv,
                         fcff=fcff, wacc=wacc[t], discount_factor=df, pv_fcff=pv,
                         invested_capital=ic, roic=nopat / ic if ic > 0 else float("nan")))
        R = R_new

    if coc.wacc_terminal <= g:
        raise ValueError("WACC terminal <= crecimiento terminal")
    nopat_t = R * (1 + g) * margin[-1] * (1 - inp["tax_marginal"])
    rr = g / inp["terminal_roic"] if inp["terminal_roic"] > 0 else 0.0
    fcff_t = nopat_t * (1 - rr)
    tv = fcff_t / (coc.wacc_terminal - g)
    pv_tv = tv / cum

    op = pv_sum + pv_tv
    p = inp["failure_prob"]
    op_adj = op * (1 - p) + p * a.distress_recovery * op if p > 0 else op

    equity = (op_adj + nz(d.cash) + nz(d.equity_investments)
              - nz(d.total_debt) - nz(d.minority_interest))
    vps = equity * d.fx_to_price / d.shares
    proj = pd.DataFrame(rows).set_index("year")

    ts = pv_tv / op if op else float("nan")
    if ts > 0.85:
        warns.append(f"El valor terminal supone el {ts:.0%} del valor operativo")
    last_roic = proj["roic"].iloc[-1]
    if last_roic == last_roic and last_roic > 0.5:
        warns.append(f"ROIC del año {N} = {last_roic:.0%}: revisar ventas/capital")
    if (proj["fcff"] < 0).all():
        warns.append("FCFF negativo en todo el horizonte")

    inp.update(terminal_fcff=fcff_t, terminal_value=tv, terminal_reinvestment_rate=rr,
               failure_adjusted_operating_value=op_adj)
    return FCFFResult(vps, equity, op_adj, pv_sum, pv_tv, ts, inp, proj, warns)
