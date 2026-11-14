"""Línea de comandos: `dcfval SAN.MC ITX.MC AAPL --out informes`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, report
from .config import load_config
from .data import cache
from .valuation import value_company


def _parse_set(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        v = v.strip()
        if v.lower() in ("true", "false"):
            out[k.strip()] = v.lower() == "true"
        elif v.lower() in ("none", "auto", ""):
            out[k.strip()] = None
        else:
            try:
                out[k.strip()] = float(v.rstrip("%")) / (100 if v.endswith("%") else 1)
                if k.strip() in ("years", "high_growth_years"):
                    out[k.strip()] = int(out[k.strip()])
            except ValueError:
                out[k.strip()] = v
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dcfval", description="Valoración DCF multi-modelo (industriales y banca)")
    p.add_argument("tickers", nargs="*", help="Tickers de Yahoo (p. ej. SAN.MC ITX.MC AAPL)")
    p.add_argument("-f", "--file", help="Fichero con un ticker por línea")
    p.add_argument("-c", "--config", help="YAML/JSON con supuestos (defaults y por ticker)")
    p.add_argument("-o", "--out", default="informes", help="Carpeta de salida (por defecto: informes)")
    p.add_argument("--model", choices=["general", "bank", "insurance"], help="Forzar modelo")
    p.add_argument("--set", action="append", metavar="CLAVE=VALOR",
                   help="Sobrescribir supuesto, p. ej. --set rf=3.2%% --set revenue_growth=0.06")
    p.add_argument("--rf", type=float, help="Tipo libre de riesgo (decimal)")
    p.add_argument("--erp", type=float, help="Prima de riesgo de mercado madura (decimal)")
    p.add_argument("--no-extras", action="store_true", help="Sin escenarios/sensibilidad/DCF inverso")
    p.add_argument("--no-sec", action="store_true", help="No consultar SEC EDGAR")
    p.add_argument("--no-cache", action="store_true", help="No usar caché en disco")
    p.add_argument("--format", default="md,json", help="Formatos: md,json")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    tickers = list(args.tickers)
    if args.file:
        tickers += [l.split("#")[0].strip() for l in Path(args.file).read_text().splitlines()
                    if l.split("#")[0].strip()]
    if not tickers:
        p.error("Indica al menos un ticker")
    if args.no_cache:
        cache.disable()

    base, per_ticker = load_config(args.config)
    cli_over = _parse_set(args.set)
    if args.rf is not None:
        cli_over["rf"] = args.rf
    if args.erp is not None:
        cli_over["erp"] = args.erp

    results, failed = [], []
    for tk in tickers:
        over = {**per_ticker.get(tk.upper(), {}), **cli_over}
        model = over.pop("model", None) or args.model
        try:
            r = value_company(tk, base, over, model=model, use_sec=not args.no_sec,
                              extras=not args.no_extras)
            results.append(r)
            if not args.quiet:
                print(report.console(r))
        except Exception as e:
            failed.append((tk, str(e)))
            print(f"\n[ERROR] {tk}: {e}", file=sys.stderr)

    out = report.write_all(results, args.out, tuple(args.format.split(",")))
    if not args.quiet:
        print(f"\nInformes en: {out.resolve()}  ({len(results)} OK, {len(failed)} con error)")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
