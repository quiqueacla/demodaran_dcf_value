"""dcfval — valoración DCF multi-modelo (FCFF para no financieras, Excess Return/DDM para banca)."""
__version__ = "1.0.0"

from .config import Assumptions, load_config  # noqa: E402
from .valuation import value_company, ValuationResult  # noqa: E402

__all__ = ["Assumptions", "load_config", "value_company", "ValuationResult", "__version__"]
