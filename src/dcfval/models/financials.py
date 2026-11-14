"""Modelos sobre fondos propios para bancos y aseguradoras (Damodaran, cap. 21).

1. Excess Return (residual income):
   Valor = FP_0 + Σ (ROE_t - Ke_t)·FP_{t-1} / (1+Ke)^t + VT
   VT_N  = (ROE_term - Ke_term)·FP_N / (Ke_term - g)
   Crecimiento de FP con retención: FP_t = FP_{t-1}·(1 + ROE_t·(1 - payout_t))
   Payout terminal coherente: 1 - g/ROE_term

2. DDM de pago total (dividendos + recompras) con crecimiento del BPA de
   consenso (si existe) en la fase de alto crecimiento: segunda opinión
   basada en expectativas del mercado.

3. P/VC justificado (Gordon): P/VC = (ROE - g)/(Ke - g)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import statistics

import pandas as pd

from ..config import Assumptions
from ..data.base import CompanyData, nz
from .discount import CostOfCapital, path


@dataclass
class EquityModelResult:
    value_per_share: float
    components: dict          # valor por acción de cada sub-modelo
    weights: dict
    inputs: dict
    projection: pd.DataFrame
    warnings: list = field(default_factory=list)


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def base_inputs(d: CompanyData, a: Assumptions, coc: CostOfCapital) -> tuple[dict, list]:
    w = []
    bv0 = nz(d.book_equity)
    if bv0 <= 0:
        raise ValueError("Fondos propios no disponibles o negativos")
    ni = nz(d.net_income)

    # ROE normalizado: 50 % actual + 50 % media histórica
    avg_bv = 0.5 * (bv0 + d.book_equity_prev) if d.book_equity_prev == d.book_equity_prev else bv0
    roe_now = ni / avg_bv if avg_bv > 0 else 0.0
    hist = []
    eqh, nih = d.equity_hist, d.net_income_hist
    for i in range(1, min(len(eqh), len(nih))):
        b = 0.5 * (eqh[i] + eqh[i - 1])
        if b > 0:
            hist.append(nih[i] / b)
    roe_hist = statistics.mean(hist[-3:]) if hist else roe_now
    if a.roe is not None:
        roe0, roe_src = a.roe, "manual"
    else:
        roe0, roe_src = 0.5 * roe_now + 0.5 * roe_hist, "50 % TTM + 50 % media 3 años"
    roe0 = _clip(roe0, -0.10, 0.35)

    if a.terminal_roe is not None:
        roe_t = a.terminal_roe
    else:
        roe_t = coc.ke_terminal + _clip(0.5 * (roe0 - coc.ke_terminal), -0.02, 0.04)

    g = coc.terminal_growth
    if roe_t <= g:
        w.append("ROE terminal <= g: el crecimiento destruye valor")

    if a.payout is not None:
        payout0 = a.payout
    elif ni > 0:
        ret = nz(d.dividends_paid) + (nz(d.buybacks) if a.include_buybacks else 0.0)
        payout0 = _clip(ret / ni, 0.0, 1.0)
    else:
        payout0 = 0.4
        w.append("Beneficio TTM negativo: payout inicial 40 % por defecto")
    payout_t = _clip(1 - g / roe_t, 0.0, 1.0) if roe_t > 0 else 1.0

    return dict(book_equity=bv0, tangible_book=d.tangible_book, net_income=ni,
                roe_ttm=roe_now, roe_hist=roe_hist, roe0=roe0, roe_source=roe_src,
                terminal_roe=roe_t, payout0=payout0, terminal_payout=payout_t,
                eps_growth_lt=d.analyst_eps_growth_lt), w


def _excess_return(inp, a: Assumptions, coc: CostOfCapital):
    N, H, g = a.years, a.high_growth_years, coc.terminal_growth
    roe = path(inp["roe0"], inp["terminal_roe"], N, H)
    pay = path(inp["payout0"], inp["terminal_payout"], N, H)
    ke = path(coc.ke, coc.ke_terminal, N, H)
    bv, cum, rows, pv_er, pv_div = inp["book_equity"], 1.0, [], 0.0, 0.0
    for t in range(N):
        ni = roe[t] * bv
        div = pay[t] * ni
        er = (roe[t] - ke[t]) * bv
        cum *= (1 + ke[t])
        pv_er += er / cum
        pv_div += div / cum
        rows.append(dict(year=t + 1, roe=roe[t], ke=ke[t], payout=pay[t], book_equity_begin=bv,
                         net_income=ni, dividends=div, excess_return=er, pv_excess_return=er / cum,
                         equity_growth=roe[t] * (1 - pay[t])))
        bv = bv + ni - div
    tv = (inp["terminal_roe"] - coc.ke_terminal) * bv / (coc.ke_terminal - g)
    value = inp["book_equity"] + pv_er + tv / cum
    return value, pd.DataFrame(rows).set_index("year"), dict(pv_excess=pv_er, pv_terminal=tv / cum,
                                                            book_equity_N=bv)


def _ddm(inp, a: Assumptions, coc: CostOfCapital, d: CompanyData):
    """DDM de pago total con crecimiento del BPA de consenso en la fase alta."""
    N, H, g = a.years, a.high_growth_years, coc.terminal_growth
    g_fund = inp["roe0"] * (1 - inp["payout0"])
    g0 = inp["eps_growth_lt"] if inp["eps_growth_lt"] is not None else g_fund
    g0 = _clip(g0, -0.05, 0.20)
    growth = path(g0, g, N, H)
    pay = path(inp["payout0"], inp["terminal_payout"], N, H)
    ke = path(coc.ke, coc.ke_terminal, N, H)
    # Beneficio base normalizado: media de TTM y ROE normalizado x FP
    norm = inp["roe0"] * inp["book_equity"]
    ni = norm if inp["net_income"] <= 0 else 0.5 * (inp["net_income"] + norm)
    cum, pv = 1.0, 0.0
    for t in range(N):
        ni *= (1 + growth[t])
        cum *= (1 + ke[t])
        pv += pay[t] * ni / cum
    div_next = ni * (1 + g) * inp["terminal_payout"]
    tv = div_next / (coc.ke_terminal - g)
    return pv + tv / cum, dict(g0=g0, g0_source="consenso BPA LP" if inp["eps_growth_lt"] is not None
                                else "fundamental ROE·(1-payout)")


def run(d: CompanyData, a: Assumptions, coc: CostOfCapital) -> EquityModelResult:
    inp, warns = base_inputs(d, a, coc)
    g = coc.terminal_growth
    if coc.ke_terminal <= g:
        raise ValueError("Ke terminal <= crecimiento terminal")

    er_val, proj, er_det = _excess_return(inp, a, coc)
    ddm_val, ddm_det = _ddm(inp, a, coc, d)
    pbv = (inp["roe0"] - g) / (coc.ke - g)
    pbv_val = inp["book_equity"] * max(pbv, 0.0)

    k = d.fx_to_price / d.shares
    comps = {"excess_return": er_val * k, "ddm": ddm_val * k, "justified_pbv": pbv_val * k}
    wts = dict(a.bank_weights)
    tot = sum(wts.get(x, 0) for x in comps)
    vps = sum(comps[x] * wts.get(x, 0) for x in comps) / tot

    mkt_pbv = d.price / (inp["book_equity"] * k)
    implied_roe = g + mkt_pbv * (coc.ke - g)
    inp.update(er_detail=er_det, ddm_detail=ddm_det, justified_pbv=pbv, market_pbv=mkt_pbv,
               market_implied_roe=implied_roe,
               market_ptbv=d.price / (nz(d.tangible_book) * k) if nz(d.tangible_book) > 0 else float("nan"))
    if inp["roe0"] < coc.ke:
        warns.append(f"ROE normalizado ({inp['roe0']:.1%}) < Ke ({coc.ke:.1%}): destruye valor")
    return EquityModelResult(vps, comps, wts, inp, proj, warns)
