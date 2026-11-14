"""Tests de coherencia matemática con datos sintéticos (sin red)."""
import math

import pytest

from dcfval import Assumptions, value_company
from dcfval.cli import _parse_set
from dcfval.data.base import CompanyData
from dcfval.models.discount import synthetic_rating, path

RF, ERP = 0.03, 0.05


def industrial(**kw):
    d = CompanyData(ticker="TEST", name="Test Ind", sector="Industrials", industry="Machinery",
                    country="Germany", currency="EUR", financial_currency="EUR",
                    price=10.0, shares=100.0, beta_regression=1.0,
                    revenue=1000.0, ebit=100.0, interest_expense=1.0, pretax_income=99.0,
                    tax_provision=29.7, net_income=69.3, total_debt=0.0, cash=0.0,
                    book_equity=500.0, revenue_hist=[1000.0] * 3, ebit_hist=[100.0] * 3)
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def bank(**kw):
    d = CompanyData(ticker="BANK", name="Test Bank", sector="Financial Services",
                    industry="Banks - Regional", country="Germany", currency="EUR",
                    financial_currency="EUR", price=10.0, shares=100.0, beta_regression=1.0,
                    net_income=80.0, book_equity=1000.0, book_equity_prev=1000.0,
                    dividends_paid=40.0, equity_hist=[1000.0] * 3, net_income_hist=[80.0] * 3)
    for k, v in kw.items():
        setattr(d, k, v)
    return d


BASE = dict(rf=RF, erp=ERP, crp=0.0, beta=1.0, mid_year=False)


def test_fcff_zero_growth_equals_perpetuity():
    a = Assumptions().merged(dict(BASE, revenue_growth=0.0, terminal_growth=0.0,
                                  target_margin=0.10, tax_rate=0.30, failure_prob=0.0))
    r = value_company("TEST", a, data=industrial(), use_sec=False, extras=False)
    assert r.model_type == "general"
    wacc = RF + ERP  # sin deuda
    nopat = 100.0 * (1 - 0.30)
    assert r.model.operating_value == pytest.approx(nopat / wacc, rel=1e-9)
    assert r.value_per_share == pytest.approx(nopat / wacc / 100.0, rel=1e-9)


def test_fcff_net_cash_added_and_debt_subtracted():
    a = Assumptions().merged(dict(BASE, revenue_growth=0.0, terminal_growth=0.0,
                                  target_margin=0.10, tax_rate=0.30, failure_prob=0.0))
    r0 = value_company("TEST", a, data=industrial(), use_sec=False, extras=False)
    r1 = value_company("TEST", a, data=industrial(cash=200.0), use_sec=False, extras=False)
    assert (r1.model.equity_value - r0.model.equity_value) == pytest.approx(200.0)


def test_growth_at_roic_equal_wacc_adds_no_value():
    """Con ROIC = WACC el crecimiento terminal no crea valor (Damodaran)."""
    wacc = RF + ERP
    a = Assumptions().merged(dict(BASE, revenue_growth=0.0, target_margin=0.10, tax_rate=0.30,
                                  failure_prob=0.0, terminal_roic=wacc, terminal_growth=0.02))
    r = value_company("TEST", a, data=industrial(), use_sec=False, extras=False)
    inp, proj = r.model.inputs, r.model.projection
    nopat_next = proj["revenue"].iloc[-1] * 1.02 * 0.10 * (1 - r.coc.tax_marginal)
    assert inp["terminal_value"] == pytest.approx(nopat_next / wacc, rel=1e-9)


def test_bank_roe_equal_ke_worth_book():
    ke = RF + ERP
    a = Assumptions().merged(dict(BASE, roe=ke, terminal_roe=ke, terminal_growth=0.02))
    r = value_company("BANK", a, data=bank(), use_sec=False, extras=False)
    assert r.model_type == "bank"
    assert r.model.components["excess_return"] == pytest.approx(10.0, rel=1e-9)  # VC/acción
    assert r.model.components["justified_pbv"] == pytest.approx(10.0, rel=1e-9)


def test_bank_higher_roe_more_value():
    a1 = Assumptions().merged(dict(BASE, roe=0.10, terminal_roe=0.09))
    a2 = Assumptions().merged(dict(BASE, roe=0.14, terminal_roe=0.11))
    v1 = value_company("BANK", a1, data=bank(), use_sec=False, extras=False).value_per_share
    v2 = value_company("BANK", a2, data=bank(), use_sec=False, extras=False).value_per_share
    assert v2 > v1


def test_insurance_classification():
    d = bank(industry="Insurance - Diversified")
    r = value_company("INS", Assumptions().merged(BASE), data=d, use_sec=False, extras=False)
    assert r.model_type == "insurance"


def test_extras_run_and_reverse_dcf_recovers_price():
    a = Assumptions().merged(dict(BASE, target_margin=0.10, tax_rate=0.30, failure_prob=0.0))
    r = value_company("TEST", a, data=industrial(), use_sec=False, extras=True)
    assert set(r.scenarios) == {"bajista", "base", "alcista"}
    assert r.scenarios["bajista"]["value_per_share"] < r.scenarios["alcista"]["value_per_share"]
    g = r.reverse.get("implied_revenue_growth")
    assert g is not None
    chk = value_company("TEST", a.merged({"revenue_growth": g}), data=industrial(),
                        use_sec=False, extras=False)
    assert chk.value_per_share == pytest.approx(10.0, rel=1e-4)
    assert r.sensitivity.shape == (5, 5)


def test_synthetic_rating():
    assert synthetic_rating(20)[0] == "AAA"
    assert synthetic_rating(2.7)[0] == "BBB"
    assert synthetic_rating(0.1)[0] == "D"


def test_path():
    p = path(0.10, 0.02, 10, 5)
    assert p[:5] == [0.10] * 5 and math.isclose(p[-1], 0.02)


def test_parse_set():
    s = _parse_set(["rf=3.2%", "years=8", "beta=auto", "include_buybacks=false"])
    assert s == {"rf": pytest.approx(0.032), "years": 8, "beta": None, "include_buybacks": False}
