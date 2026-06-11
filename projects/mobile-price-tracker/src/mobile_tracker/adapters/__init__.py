from .base import BaseAdapter
from .vivo import VivoAdapter
from .claro import ClaroAdapter
from .tim import TimAdapter

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "vivo": VivoAdapter,
    "claro": ClaroAdapter,
    "tim": TimAdapter,
}

__all__ = ["BaseAdapter", "VivoAdapter", "ClaroAdapter", "TimAdapter", "ADAPTERS"]
