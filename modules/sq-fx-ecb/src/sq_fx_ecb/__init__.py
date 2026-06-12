"""sq-fx-ecb — ECB EUR-cross FX rates as a `sq_schema.FxRateProvider`."""
from .provider import (
    ECBProvider, ECB_DAILY_URL, ECB_HIST_90D_URL, ECB_HIST_FULL_URL,
)

__all__ = ["ECBProvider", "ECB_DAILY_URL", "ECB_HIST_90D_URL",
           "ECB_HIST_FULL_URL"]
