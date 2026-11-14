# dcfval — Valoración DCF multi-modelo (industriales y banca)

Paquete Python que descarga datos gratuitos (Yahoo Finance y otras fuentes) y valora
compañías por descuento de flujos eligiendo **el modelo adecuado según el tipo de empresa**:

| Tipo (detectado por industria Yahoo) | Modelo |
|---|---|
| Industriales, consumo, tecnología, salud, energía, utilities… | **FCFF a 2 etapas** (Damodaran): crecimiento → convergencia, reinversión vía *ventas/capital*, ROIC terminal coherente |
| Bancos (Banks-*, Credit Services, Mortgage Finance) | **Excess Return** + **DDM de pago total** + **P/VC justificado** |
| Aseguradoras (Insurance-*) | Igual que bancos |

Para cada ticker genera: valor intrínseco por acción, potencial, precio de compra con margen
de seguridad, veredicto, **escenarios bajista/base/alcista**, **tabla de sensibilidad**
(tasa de descuento × g) y **DCF inverso** (qué crecimiento / WACC / ROE descuenta el precio).

> ⚠️ Herramienta educativa. No es una recomendación de inversión.

---

## Instalación

```bash
git clone https://github.com/<tu-usuario>/dcfval.git   # o descomprime el zip
cd dcfval
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                                          # añade [dev] para tests: pip install -e ".[dev]"
```

Requiere Python ≥ 3.9. Dependencias: `yfinance`, `pandas`, `numpy`, `requests`, `pyyaml`, `openpyxl`.

## Uso rápido

```bash
dcfval SAN.MC ITX.MC AAPL                 # informes en ./informes
dcfval -f tickers.example.txt -o informes # lista desde fichero
dcfval -c config.example.yaml -f tickers.example.txt
dcfval IAG.MC --set target_margin=7% --set revenue_growth=4%
dcfval XYZ --model bank                   # forzar modelo
python -m dcfval MAP.MC --no-extras       # sin escenarios/sensibilidad (más rápido)
```

Salida en la carpeta indicada:

- `TICKER.md` — informe completo legible (ideal para pasárselo a Claude/ChatGPT y comentarlo)
- `TICKER.json` — todos los datos, supuestos y proyecciones (para análisis posterior)
- `resumen.md` / `resumen.csv` — ranking ordenado por potencial

### Desde Python

```python
from dcfval import value_company, Assumptions
r = value_company("SAN.MC", overrides={"crp": 0.022})
print(r.value_per_share, r.upside, r.verdict)
print(r.model.projection)      # DataFrame con la proyección
print(r.sensitivity)           # tabla de sensibilidad
```

### Supuestos sobrescribibles (`--set clave=valor` o YAML)

| Clave | Por defecto | Descripción |
|---|---|---|
| `years`, `high_growth_years` | 10, 5 | Horizonte y años de crecimiento alto |
| `rf` | auto por divisa | Tipo libre de riesgo |
| `erp` | 4,17 % | Prima de riesgo de mercado madura (Damodaran jul-2026) |
| `crp`, `crp_lambda` | por país, 1 | Prima de riesgo país y exposición |
| `beta`, `beta_method` | auto, blend | `regression` (Blume), `bottom_up` (sector reapalancado) o media |
| `terminal_growth`, `terminal_growth_cap` | min(Rf, 2,5 %) | Crecimiento perpetuo |
| `terminal_beta_min/max` | 0,8 / 1,2 | Beta en crecimiento estable |
| `revenue_growth` | consenso → CAGR | Crecimiento inicial de ingresos |
| `target_margin` | media actual/histórica | Margen EBIT objetivo |
| `sales_to_capital` | histórico | Euros de ventas por euro invertido |
| `terminal_roic` | WACC + ½ exceso (máx +5 pp) | ROIC en estable |
| `cyclical`, `cyclical_margin_years` | por industria, 3 | Normalización de márgenes en cíclicas |
| `failure_prob`, `distress_recovery` | por rating, 50 % | Ajuste por probabilidad de quiebra |
| `roe`, `terminal_roe` | normalizado / Ke + ½ exceso | Bancos y aseguradoras |
| `payout`, `include_buybacks` | histórico, true | Retorno total al accionista |
| `bank_weights` | 50/30/20 | Peso de Excess Return / DDM / P/VC |
| `margin_of_safety` | 25 % | Para el precio de compra y el veredicto |

---

## Metodología

### 1. Coste de capital

- **Ke = Rf + β·ERP + λ·CRP** (CAPM con prima de riesgo país de Damodaran).
- **Rf** por divisa de los estados financieros: USD → Treasury 10a (Yahoo `^TNX`, respaldo FRED);
  EUR → curva AAA zona euro 10a del BCE; otras → tabla de respaldo.
- **β**: media de la beta de regresión ajustada de Blume (0,67·β + 0,33) y la beta *bottom-up*
  (beta desapalancada del sector reapalancada con D/E de mercado). En estable se acota a [0,8; 1,2].
- **Coste de la deuda**: Rf + spread del **rating sintético** según cobertura de intereses
  (tabla de Damodaran para grandes empresas), después de impuestos al tipo marginal del país.
- **WACC** con pesos de mercado; converge linealmente a su valor terminal tras la fase de alto crecimiento.

### 2. Empresas no financieras — FCFF

```
Ingresos_t  = Ingresos_{t-1} · (1 + g_t)       g: g0 durante 5 años → g terminal en el año 10
EBIT_t      = Ingresos_t · margen_t            margen: actual → objetivo
NOPAT_t     = EBIT_t · (1 - t_t)               t: efectivo → marginal
Reinversión = ΔIngresos_t / (Ventas/Capital)
FCFF_t      = NOPAT_t - Reinversión_t
VT_N        = NOPAT_{N+1} · (1 - g/ROIC_term) / (WACC_term - g)
Valor FFPP  = VA(FCFF) + VA(VT) [ajustado por quiebra] + caja + participadas - deuda - minoritarios
```

La tasa de reinversión terminal `g/ROIC` garantiza que el crecimiento perpetuo se "paga"
con inversión (si ROIC = WACC, el crecimiento no añade valor). Convención de mitad de año.
En **industrias cíclicas** el margen se normaliza a la media disponible y converge en 3 años.

### 3. Bancos y aseguradoras — modelos sobre fondos propios

En financieras la deuda es materia prima, no financiación, y la inversión en capital
circulante/CAPEX no está definida, así que no se calcula FCFF/WACC. Se descuenta a **Ke**:

1. **Excess Return**: `Valor = FP₀ + Σ (ROE_t − Ke)·FP_{t−1}/(1+Ke)^t + VT`, con
   `VT = (ROE_term − Ke)·FP_N/(Ke − g)` y payout terminal coherente `1 − g/ROE_term`.
2. **DDM de pago total** (dividendos + recompras) con crecimiento del BPA de consenso en la fase alta.
3. **P/VC justificado**: `(ROE − g)/(Ke − g)` × valor contable.

ROE inicial normalizado (50 % TTM + 50 % media de 3 años). El informe muestra además el
**ROE implícito en el precio** y el P/VC tangible.

### 4. Análisis adicional

- **Escenarios**: bajista (menos crecimiento, −15 % margen, +1 pp tasa) / base / alcista.
  En bancos: ±2 pp de ROE.
- **Sensibilidad**: tasa de descuento ±1 pp × g ±1 pp.
- **DCF inverso**: crecimiento de ingresos y WACC implícitos en el precio (FCFF) o ROE sostenido implícito (bancos).
- **Avisos de calidad**: VT > 85 % del valor, ROIC final > 50 %, FCFF negativo, TTM anómalo frente
  al último anual, márgenes de pico/valle, discrepancias Yahoo vs SEC, divisas distintas.

## Fuentes de datos (gratuitas, sin API key)

| Fuente | Uso |
|---|---|
| Yahoo Finance (`yfinance`) | Precio, estados financieros anuales y trimestrales, beta, consenso de analistas, FX |
| BCE Data API | Rf EUR (curva AAA 10 años) |
| FRED (St. Louis Fed) | Rf USD de respaldo (DGS10) |
| SEC EDGAR XBRL | Contraste de acciones y patrimonio en emisores de EE. UU. (define `DCFVAL_SEC_UA="Nombre email"`) |
| Damodaran Online (`ctryprem.xlsx`) | Primas de riesgo país; tabla embebida (ene-2026) como respaldo |

Caché diaria en `~/.cache/dcfval` (desactivar con `--no-cache` o `DCFVAL_NO_CACHE=1`).

## Limitaciones conocidas

- Yahoo ofrece ~4 ejercicios anuales: en **cíclicas** (aerolíneas, petroleras, acero…) la media
  puede no ser un ciclo completo. Fija `target_margin` en el YAML.
- La CRP se aplica por país de domicilio; para multinacionales con negocio en emergentes
  (Santander, BBVA, Telefónica…) conviene fijar una `crp` ponderada por ingresos.
- Bancos: no se dispone de CET1 ni de exceso de capital regulatorio; el ROE y el payout recogen
  implícitamente esa política.
- Utilities reguladas y REITs se valoran con FCFF; para ellas un enfoque por base regulatoria
  (RAB) o por AFFO puede ser más apropiado.
- Los datos de Yahoo a veces contienen trimestres acumulados o huecos: revisa los avisos.

## Bibliografía y referencias

- Damodaran, A. *Investment Valuation*, 3ª ed., Wiley (2012) — caps. 7-8 (coste de capital),
  11-12 (crecimiento y valor terminal), 15 (FCFF), 21 (*Valuing Financial Service Firms*).
- Damodaran, A. (2013). "Valuing Financial Service Firms". *Journal of Financial Perspectives* 1(1), 59-74.
- Damodaran, A. (2009). "Breach of Trust: Valuing Financial Service Firms in the Post-Crisis Era". SSRN 1798578.
- Damodaran, A. "Country Risk: Drivers, Measures and Implications — The 2026 Edition" (julio 2026).
- Damodaran, A. "Equity Risk Premiums: Determinants, Estimation and Implications — 2026 Edition".
- Damodaran Online, datos: https://pages.stern.nyu.edu/~adamodar/ (ERP, CRP, ratings sintéticos, betas sectoriales).
- Koller, Goedhart, Wessels (McKinsey). *Valuation: Measuring and Managing the Value of Companies*, 7ª ed. (2020).
- Blume, M. (1975). "Betas and Their Regression Tendencies". *Journal of Finance* 30(3).
- Ohlson, J. (1995). "Earnings, Book Values, and Dividends in Equity Valuation". *Contemporary Accounting Research* (modelo de beneficio residual).

## Tests

```bash
pip install -e ".[dev]" && pytest -q
```

Comprueban identidades del modelo con datos sintéticos (perpetuidad sin crecimiento, ROIC = WACC
no crea valor, banco con ROE = Ke vale su valor contable, DCF inverso recupera el precio…).

## Licencia

MIT
