"""Clasifica la compañía para elegir el modelo de valoración adecuado."""
from __future__ import annotations

from ..data.base import CompanyData

BANK_INDUSTRIES = ("Banks", "Credit Services", "Mortgage Finance", "Savings", "Thrift")
INSURANCE_INDUSTRIES = ("Insurance - Life", "Insurance - Property", "Insurance - Diversified",
                        "Insurance - Reinsurance", "Insurance - Specialty")


def classify(d: CompanyData, forced: str | None = None) -> str:
    """Devuelve 'bank', 'insurance' o 'general' (FCFF).

    - bank / insurance -> modelos sobre fondos propios (Excess Return, DDM, P/VC
      justificado), porque la deuda es materia prima y el FCFF no está definido.
    - general -> FCFF a 2 etapas (industriales, consumo, tecnología, utilities,
      inmobiliarias, gestoras y brókeres de seguros basados en comisiones).
    """
    if forced:
        return forced
    ind = d.industry or ""
    if any(ind.startswith(x) for x in BANK_INDUSTRIES):
        return "bank"
    if any(ind.startswith(x) for x in INSURANCE_INDUSTRIES):
        return "insurance"
    if d.sector == "Financial Services" and ind in ("Financial Conglomerates",):
        return "bank"
    return "general"
