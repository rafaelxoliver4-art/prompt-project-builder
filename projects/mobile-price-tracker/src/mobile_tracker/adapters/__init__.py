from .base import BaseAdapter
from .vivo import VivoAdapter
from .claro import ClaroAdapter
from .tim import TimAdapter
from .tim_convergent import TimConvergentAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "vivo": VivoAdapter,
    "claro": ClaroAdapter,
    "tim": TimAdapter,
}

# CONVERGENT (combo) adapters — a separate registry keyed by the `adapter:` name in the config's
# `convergent:` section (#31, CONTEXT §14). Kept apart from ADAPTERS so the mobile pipeline can
# never accidentally pick up a convergent adapter (they return ConvergentOffer, not Plan).
CONVERGENT_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "tim_ultracombo": TimConvergentAdapter,
    # phase 2: "vivo_total": VivoTotalAdapter, "claro_multi": ClaroMultiAdapter
}

__all__ = ["BaseAdapter", "VivoAdapter", "ClaroAdapter", "TimAdapter", "TimConvergentAdapter",
           "ADAPTERS", "CONVERGENT_ADAPTERS"]
