"""Informes: consola, Markdown por ticker, JSON y resumen CSV/Markdown."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .valuation import ValuationResult

MODEL_NAMES = {
    "general": "FCFF 2 etapas (Damodaran)",
    "bank": "Banco: Excess Return + DDM + P/VC justificado",
    "insurance": "Aseguradora: Excess Return + DDM + P/VC justificado",
}


def _p(x, d=1):
    return "n/d" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.{d}f} %"


def _n(x, d=2):
    return "n/d" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:,.{d}f}"


def _m(x):
    """Millones."""
    return "n/d" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x / 1e6:,.0f}"


def _beta_txt(det: dict) -> str:
    parts = [f"método {det.get('method')}"]
    if "regression_raw" in det:
        parts.append(f"regresión {det['regression_raw']:.2f} (Blume {det['regression_blume']:.2f})")
    if "unlevered_sector" in det:
        parts.append(f"bottom-up βu {det['unlevered_sector']:.2f}, D/E {det['debt_to_equity']:.1%} "
                     f"→ {det['bottom_up']:.2f}")
    elif "bottom_up" in det:
        parts.append(f"referencia sector {det['bottom_up']:.2f}")
    return "; ".join(parts)


def summary_row(r: ValuationResult) -> dict:
    return {
        "ticker": r.ticker, "nombre": r.name, "modelo": r.model_type, "divisa": r.currency,
        "precio": round(r.price, 4), "valor_intrinseco": round(r.value_per_share, 4),
        "potencial": round(r.upside, 4), "comprar_por_debajo_de": round(r.buy_below, 4),
        "veredicto": r.verdict,
        "bajista": round(r.scenarios.get("bajista", {}).get("value_per_share", float("nan")), 4),
        "alcista": round(r.scenarios.get("alcista", {}).get("value_per_share", float("nan")), 4),
        "tasa_descuento": round(r.coc.ke if r.model_type != "general" else r.coc.wacc, 4),
        "g_terminal": round(r.coc.terminal_growth, 4),
        "fecha": r.date,
    }


def console(r: ValuationResult) -> str:
    rate = ("Ke", r.coc.ke) if r.model_type != "general" else ("WACC", r.coc.wacc)
    lines = [
        f"\n=== {r.ticker} — {r.name} ===",
        f"Modelo: {MODEL_NAMES[r.model_type]}  |  {r.data.sector} / {r.data.industry} / {r.data.country}",
        f"Precio: {_n(r.price)} {r.currency}   Valor intrínseco: {_n(r.value_per_share)} {r.currency}"
        f"   Potencial: {_p(r.upside)}",
        f"Comprar por debajo de (MoS {r.assumptions.margin_of_safety:.0%}): {_n(r.buy_below)}",
        f"Veredicto: {r.verdict}",
        f"{rate[0]}: {_p(rate[1], 2)}  Rf: {_p(r.coc.rf, 2)}  Beta: {r.coc.beta:.2f}  "
        f"ERP: {_p(r.coc.erp, 2)}  CRP: {_p(r.coc.crp, 2)}  g: {_p(r.coc.terminal_growth, 2)}",
    ]
    if r.scenarios:
        sc = "  ".join(f"{k}: {_n(v.get('value_per_share', float('nan')))}" for k, v in r.scenarios.items())
        lines.append(f"Escenarios -> {sc}")
    if r.reverse:
        rv = "  ".join(f"{k}: {_p(v) if isinstance(v, float) else v}" for k, v in r.reverse.items())
        lines.append(f"DCF inverso -> {rv}")
    for w in r.warnings:
        lines.append(f"  ! {w}")
    return "\n".join(lines)


def markdown(r: ValuationResult) -> str:
    d, c, a, m = r.data, r.coc, r.assumptions, r.model
    out = [f"# Valoración {r.ticker} — {r.name}", "",
           f"*Fecha: {r.date} · Modelo: {MODEL_NAMES[r.model_type]} · Fuentes: {', '.join(d.sources)}*", "",
           "## Resultado", "",
           "| Concepto | Valor |", "|---|---|",
           f"| Sector / industria / país | {d.sector} / {d.industry} / {d.country} |",
           f"| Precio actual | {_n(r.price)} {r.currency} |",
           f"| **Valor intrínseco por acción** | **{_n(r.value_per_share)} {r.currency}** |",
           f"| Potencial | {_p(r.upside)} |",
           f"| Precio de compra con MoS {a.margin_of_safety:.0%} | {_n(r.buy_below)} {r.currency} |",
           f"| **Veredicto** | **{r.verdict}** |", ""]

    out += ["## Coste de capital", "", "| Parámetro | Valor | Fuente / detalle |", "|---|---|---|",
            f"| Tipo libre de riesgo ({d.financial_currency}) | {_p(c.rf, 2)} | {c.sources.get('rf')} |",
            f"| Prima de riesgo madura (ERP) | {_p(c.erp, 2)} | Damodaran |",
            f"| Prima riesgo país (CRP × λ={a.crp_lambda}) | {_p(c.crp, 2)} | {c.sources.get('crp')} |",
            f"| Beta | {c.beta:.2f} | {_beta_txt(c.beta_detail)} |",
            f"| Coste de recursos propios (Ke) | {_p(c.ke, 2)} | Rf + β·ERP + CRP |"]
    if r.model_type == "general":
        out += [f"| Cobertura intereses / rating sintético | {_n(c.coverage, 1)}x / {c.rating} | tabla Damodaran |",
                f"| Coste deuda antes / después impuestos | {_p(c.kd_pre, 2)} / {_p(c.kd_after, 2)} | t marginal {_p(c.tax_marginal, 1)} |",
                f"| Pesos E / D (mercado) | {_p(c.we)} / {_p(c.wd)} | |",
                f"| **WACC** inicial → terminal | **{_p(c.wacc, 2)} → {_p(c.wacc_terminal, 2)}** | β estable {c.beta_detail.get('beta_terminal', 1):.2f} |"]
    else:
        out += [f"| Ke terminal | {_p(c.ke_terminal, 2)} | β estable {c.beta_detail.get('beta_terminal', 1):.2f} |"]
    out += [f"| Crecimiento terminal (g) | {_p(c.terminal_growth, 2)} | ≤ Rf, tope {_p(a.terminal_growth_cap, 1)} |", ""]

    out += ["## Supuestos clave", "", "| Supuesto | Valor |", "|---|---|"]
    inp = m.inputs
    if r.model_type == "general":
        out += [f"| Ingresos TTM (M {d.financial_currency}) | {_m(inp['R0'])} |",
                f"| Crecimiento inicial ingresos | {_p(inp['g0'])} ({inp['g0_source']}) |",
                f"| Margen EBIT actual / media 3a / objetivo | {_p(inp['margin0'])} / {_p(inp['margin_hist_avg'])} / {_p(inp['target_margin'])} |",
                f"| Tipo impositivo efectivo → marginal | {_p(inp['tax0'])} → {_p(inp['tax_marginal'])} |",
                f"| Ventas / capital invertido | {_n(inp['sales_to_capital'])} ({inp['s2c_source']}) |",
                f"| ROIC actual / terminal | {_p(inp['roic0'])} / {_p(inp['terminal_roic'])} |",
                f"| Tasa de reinversión terminal (g/ROIC) | {_p(inp['terminal_reinvestment_rate'])} |",
                f"| Probabilidad de quiebra | {_p(inp['failure_prob'])} |", "",
                "## Puente de valor (M " + d.financial_currency + ")", "",
                "| Partida | Importe |", "|---|---|",
                f"| VA flujos explícitos | {_m(m.pv_fcff)} |",
                f"| VA valor terminal | {_m(m.pv_terminal)} ({_p(m.terminal_share)} del total) |",
                f"| Valor operativo (ajustado quiebra) | {_m(m.operating_value)} |",
                f"| + Caja e inversiones c/p | {_m(d.cash)} |",
                f"| + Participadas | {_m(d.equity_investments)} |",
                f"| − Deuda (incl. arrendamientos) | {_m(d.total_debt)} |",
                f"| − Minoritarios | {_m(d.minority_interest)} |",
                f"| **Valor de los fondos propios** | **{_m(m.equity_value)}** |",
                f"| Acciones (M) | {_n(d.shares / 1e6, 1)} |", ""]
        cols = ["growth", "revenue", "ebit_margin", "ebit", "tax_rate", "nopat", "reinvestment",
                "fcff", "wacc", "pv_fcff", "roic"]
    else:
        out += [f"| Fondos propios (M {d.financial_currency}) | {_m(inp['book_equity'])} |",
                f"| Valor contable tangible (M) | {_m(inp['tangible_book'])} |",
                f"| Beneficio neto TTM (M) | {_m(inp['net_income'])} |",
                f"| ROE TTM / media hist. / normalizado | {_p(inp['roe_ttm'])} / {_p(inp['roe_hist'])} / {_p(inp['roe0'])} |",
                f"| ROE terminal | {_p(inp['terminal_roe'])} |",
                f"| Payout total inicial → terminal | {_p(inp['payout0'])} → {_p(inp['terminal_payout'])} |",
                f"| P/VC mercado / P/VC justificado | {_n(inp['market_pbv'])} / {_n(inp['justified_pbv'])} |",
                f"| P/VC tangible mercado | {_n(inp['market_ptbv'])} |",
                f"| ROE implícito en el precio | {_p(inp['market_implied_roe'])} |", "",
                "## Sub-modelos (por acción)", "", "| Modelo | Valor | Peso |", "|---|---|---|"]
        for k, v in m.components.items():
            out.append(f"| {k} | {_n(v)} | {m.weights.get(k, 0):.0%} |")
        out.append("")
        cols = ["roe", "ke", "payout", "book_equity_begin", "net_income", "dividends",
                "excess_return", "pv_excess_return"]

    out += ["## Proyección", "", _table(m.projection[cols]), ""]

    if r.scenarios:
        out += ["## Escenarios", "", "| Escenario | Valor/acción | Potencial | Supuestos |", "|---|---|---|---|"]
        for k, v in r.scenarios.items():
            vps = v.get("value_per_share", float("nan"))
            sup = ", ".join(f"{kk}={_p(vv) if isinstance(vv, float) else vv}" for kk, vv in v.items()
                            if kk != "value_per_share")
            out.append(f"| {k} | {_n(vps)} | {_p(vps / r.price - 1)} | {sup} |")
        out.append("")
    if r.sensitivity is not None:
        out += ["## Sensibilidad (valor por acción)", "", _table(r.sensitivity, money=True), ""]
    if r.reverse:
        out += ["## DCF inverso (lo que descuenta el precio)", ""]
        for k, v in r.reverse.items():
            out.append(f"- **{k}**: {_p(v) if isinstance(v, float) else v}")
        out.append("")
    if r.warnings:
        out += ["## Avisos", ""] + [f"- {w}" for w in r.warnings] + [""]
    out += ["---", "*Modelo educativo, no constituye recomendación de inversión.*"]
    return "\n".join(out)


def _table(df: pd.DataFrame, money=False) -> str:
    pct = {"growth", "ebit_margin", "tax_rate", "wacc", "roic", "roe", "ke", "payout", "equity_growth"}
    hdr = "| " + " | ".join([str(df.index.name or "")] + [str(c) for c in df.columns]) + " |"
    sep = "|" + "---|" * (len(df.columns) + 1)
    rows = [hdr, sep]
    for idx, row in df.iterrows():
        cells = []
        for c, v in row.items():
            if money:
                cells.append(_n(v))
            elif c in pct:
                cells.append(_p(v))
            else:
                cells.append(_m(v))
        rows.append(f"| {idx} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def to_json(r: ValuationResult) -> dict:
    def clean(o):
        if isinstance(o, float) and math.isnan(o):
            return None
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        return o
    m = r.model
    payload = {
        "summary": summary_row(r),
        "cost_of_capital": r.coc.to_dict(),
        "assumptions": r.assumptions.to_dict(),
        "inputs": m.inputs,
        "components": getattr(m, "components", None),
        "projection": m.projection.reset_index().to_dict(orient="records"),
        "scenarios": r.scenarios,
        "sensitivity": r.sensitivity.to_dict() if r.sensitivity is not None else None,
        "reverse_dcf": r.reverse,
        "warnings": r.warnings,
        "company_data": r.data.to_dict(),
    }
    return clean(payload)


def write_all(results: list[ValuationResult], out_dir: str | Path, fmt=("md", "json")) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for r in results:
        safe = r.ticker.replace("^", "").replace("/", "_")
        if "md" in fmt:
            (out / f"{safe}.md").write_text(markdown(r), encoding="utf-8")
        if "json" in fmt:
            (out / f"{safe}.json").write_text(json.dumps(to_json(r), indent=2, ensure_ascii=False,
                                                         default=str), encoding="utf-8")
    if results:
        df = pd.DataFrame([summary_row(r) for r in results]).sort_values("potencial", ascending=False)
        df.to_csv(out / "resumen.csv", index=False)
        lines = ["# Resumen de valoraciones", "",
                 "| Ticker | Nombre | Modelo | Precio | Valor | Potencial | Comprar < | Veredicto |",
                 "|---|---|---|---|---|---|---|---|"]
        for _, x in df.iterrows():
            lines.append(f"| {x.ticker} | {x.nombre} | {x.modelo} | {_n(x.precio)} {x.divisa} | "
                         f"{_n(x.valor_intrinseco)} | {_p(x.potencial)} | {_n(x.comprar_por_debajo_de)} | {x.veredicto} |")
        (out / "resumen.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
