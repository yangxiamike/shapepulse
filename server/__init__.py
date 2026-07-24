"""Local-only market screening backend.

The industry-radar calculation module intentionally remains importable without
the optional LocalPro runtime.  This lets its deterministic tests run in a
plain analytics environment; the application service is loaded only when an
API caller actually requests it.
"""

__all__ = ["MarketService"]


def __getattr__(name: str):
    if name == "MarketService":
        from .service import MarketService

        return MarketService
    raise AttributeError(name)
