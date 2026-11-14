"""Proveedor principal: Yahoo Finance vía `yfinance` (gratuito, sin API key)."""
from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

from . import cache
from .base import CompanyData, nz

SUBUNIT_CURRENCIES = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0),
                      "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


def _row(df: pd.DataFrame | None, names: Iterable[str]) -> pd.Series | None:
    """Primera fila existente, ordenada de antiguo a reciente, sin NaN."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            s = df.loc[n]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[0]
            s = pd.to_numeric(s, errors="coerce").sort_index().dropna()
            if len(s):
                return s
    return None


def _last(df, names, default=float("nan")) -> float:
    s = _row(df, names)
    return float(s.iloc[-1]) if s is not None else default


def _prev(df, names, default=float("nan")) -> float:
    s = _row(df, names)
    return float(s.iloc[-2]) if s is not None and len(s) >= 2 else default


def _ttm(qdf, adf, names) -> float:
    """Suma de los 4 últimos trimestres si están completos; si no, último anual."""
    s = _row(qdf, names)
    if s is not None and len(s) >= 4:
        last4 = s.iloc[-4:]
        # los 4 trimestres deben ser consecutivos (~1 año)
        span = (last4.index[-1] - last4.index[0]).days
        if 250 <= span <= 300:
            return float(last4.sum())
    # Emisores semestrales (habitual en Europa): 2 semestres consecutivos
    if s is not None and len(s) >= 2:
        last2 = s.iloc[-2:]
        if 170 <= (last2.index[-1] - last2.index[0]).days <= 195:
            a_last = _row(adf, names)
            if a_last is None or last2.index[-1] > a_last.index[-1]:
                return float(last2.sum())
    return _last(adf, names)


def _hist(df, names, n=5) -> list:
    s = _row(df, names)
    return [float(x) for x in s.iloc[-n:]] if s is not None else []


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def fx_rate(from_ccy: str, to_ccy: str) -> float:
    if not from_ccy or not to_ccy or from_ccy == to_ccy:
        return 1.0
    import yfinance as yf
    key = f"fx:{from_ccy}{to_ccy}"
    hit = cache.get(key)
    if hit:
        return hit
    rate = _safe(lambda: float(yf.Ticker(f"{from_ccy}{to_ccy}=X").history(period="5d")["Close"].iloc[-1]))
    if not rate or math.isnan(rate):
        raise RuntimeError(f"No se pudo obtener el tipo de cambio {from_ccy}->{to_ccy}")
    cache.put(key, rate)
    return rate


def fetch(ticker: str) -> CompanyData:
    key = f"yahoo:{ticker.upper()}"
    hit = cache.get(key)
    if hit is not None:
        return hit

    import yfinance as yf
    t = yf.Ticker(ticker)
    info = _safe(lambda: t.info, {}) or {}
    if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None
                    and info.get("previousClose") is None):
        raise ValueError(f"Yahoo no devuelve datos para '{ticker}'")

    inc = _safe(lambda: t.income_stmt)
    qinc = _safe(lambda: t.quarterly_income_stmt)
    bs = _safe(lambda: t.balance_sheet)
    qbs = _safe(lambda: t.quarterly_balance_sheet)
    cf = _safe(lambda: t.cashflow)
    qcf = _safe(lambda: t.quarterly_cashflow)

    # Balance más reciente: trimestral si existe, si no anual
    bsl = qbs if qbs is not None and not qbs.empty else bs

    d = CompanyData(ticker=ticker.upper())
    d.sources.append("Yahoo Finance (yfinance)")
    d.name = info.get("longName") or info.get("shortName") or ticker
    d.sector = info.get("sector") or ""
    d.industry = info.get("industry") or ""
    d.country = info.get("country") or ""

    cur = info.get("currency") or "USD"
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    if cur in SUBUNIT_CURRENCIES:
        cur, div = SUBUNIT_CURRENCIES[cur]
        price = price / div
    d.currency = cur
    d.price = float(price)
    d.financial_currency = info.get("financialCurrency") or cur
    if d.financial_currency != d.currency:
        d.fx_to_price = fx_rate(d.financial_currency, d.currency)
        d.warnings.append(f"Estados en {d.financial_currency}, cotización en {d.currency} "
                          f"(FX {d.fx_to_price:.4f})")

    # Acciones: con varias clases (Puig, Grifols...) `sharesOutstanding` sólo
    # recoge una; `impliedSharesOutstanding` las incluye todas.
    so, imp = nz(info.get("sharesOutstanding")), nz(info.get("impliedSharesOutstanding"))
    shares = max(so, imp)
    if not shares:
        shares = _last(bsl, ["Ordinary Shares Number", "Share Issued"])
    if so and imp and imp > so * 1.10:
        d.warnings.append(f"Varias clases de acciones: se usan {imp / 1e6:,.0f} M (todas las clases) "
                          f"en lugar de {so / 1e6:,.0f} M; el precio de referencia es el de {ticker}")
    d.shares = float(shares)
    d.market_cap = d.price * d.shares
    d.beta_regression = info.get("beta")

    # --- Resultados (TTM)
    d.revenue = _ttm(qinc, inc, ["Total Revenue", "Operating Revenue"])
    d.ebit = _ttm(qinc, inc, ["Operating Income", "EBIT", "Total Operating Income As Reported"])
    d.interest_expense = abs(nz(_ttm(qinc, inc, ["Interest Expense", "Interest Expense Non Operating"])))
    d.pretax_income = _ttm(qinc, inc, ["Pretax Income"])
    d.tax_provision = _ttm(qinc, inc, ["Tax Provision"])
    d.net_income = _ttm(qinc, inc, ["Net Income Common Stockholders", "Net Income"])
    d.depreciation = _ttm(qcf, cf, ["Depreciation And Amortization", "Reconciled Depreciation",
                                    "Depreciation Amortization Depletion"])

    # --- Flujo de caja
    d.capex = -nz(_ttm(qcf, cf, ["Capital Expenditure"]))
    d.delta_wc = -nz(_ttm(qcf, cf, ["Change In Working Capital"]))
    d.dividends_paid = abs(nz(_ttm(qcf, cf, ["Cash Dividends Paid", "Common Stock Dividend Paid"])))
    rep = nz(_ttm(qcf, cf, ["Repurchase Of Capital Stock", "Common Stock Payments"]))
    iss = nz(_ttm(qcf, cf, ["Issuance Of Capital Stock", "Common Stock Issuance"]))
    d.buybacks = max(0.0, -(rep + iss))
    d.fcf_reported = _ttm(qcf, cf, ["Free Cash Flow"])

    # --- Balance
    d.total_debt = nz(_last(bsl, ["Total Debt"]), nz(info.get("totalDebt")))
    d.cash = nz(_last(bsl, ["Cash Cash Equivalents And Short Term Investments",
                            "Cash And Cash Equivalents", "Cash Financial"]), nz(info.get("totalCash")))
    d.minority_interest = nz(_last(bsl, ["Minority Interest"]))
    d.equity_investments = nz(_last(bsl, ["Long Term Equity Investment", "Investments In Other Ventures Under Equity Method"]))
    d.book_equity = _last(bsl, ["Common Stock Equity", "Stockholders Equity"])
    d.book_equity_prev = _prev(bs, ["Common Stock Equity", "Stockholders Equity"])
    d.tangible_book = _last(bsl, ["Tangible Book Value"])
    d.total_assets = _last(bsl, ["Total Assets"])

    # --- Históricos anuales
    d.revenue_hist = _hist(inc, ["Total Revenue", "Operating Revenue"])
    d.ebit_hist = _hist(inc, ["Operating Income", "EBIT"])
    d.net_income_hist = _hist(inc, ["Net Income Common Stockholders", "Net Income"])
    d.equity_hist = _hist(bs, ["Common Stock Equity", "Stockholders Equity"])
    eq = _row(bs, ["Common Stock Equity", "Stockholders Equity"])
    debt = _row(bs, ["Total Debt"])
    cash = _row(bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"])
    if eq is not None:
        ic = eq.copy()
        if debt is not None:
            ic = ic.add(debt.reindex(ic.index).fillna(0), fill_value=0)
        if cash is not None:
            ic = ic.sub(cash.reindex(ic.index).fillna(0), fill_value=0)
        d.invested_capital_hist = [float(x) for x in ic.iloc[-5:]]

    # --- Consenso
    re = _safe(lambda: t.revenue_estimate)
    if re is not None and not re.empty and "growth" in re.columns:
        for p in ("+1y", "0y"):
            if p in re.index and pd.notna(re.loc[p, "growth"]):
                d.analyst_revenue_growth = float(re.loc[p, "growth"])
                break
    ge = _safe(lambda: t.growth_estimates)
    if ge is not None and not ge.empty and "LTG" in ge.index:
        col = "stockTrend" if "stockTrend" in ge.columns else ge.columns[0]
        v = ge.loc["LTG", col]
        if pd.notna(v):
            d.analyst_eps_growth_lt = float(v)

    # Control de calidad: TTM frente al último ejercicio anual
    if d.revenue_hist and d.revenue == d.revenue and d.revenue_hist[-1] > 0:
        dev = d.revenue / d.revenue_hist[-1] - 1
        if abs(dev) > 0.30:
            d.warnings.append(f"Ingresos TTM {dev:+.0%} frente al último anual: verificar "
                              "trimestres de Yahoo (posible dato acumulado o cambio de ciclo)")

    d.dividend_per_share = nz(info.get("dividendRate"))
    cache.put(key, d)
    return d
