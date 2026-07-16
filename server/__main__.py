from __future__ import annotations

import argparse
from dataclasses import replace

from .config import load_settings
from .http import serve
from .service import MarketService


def main() -> None:
    defaults = load_settings()
    parser = argparse.ArgumentParser(description="手动跟踪市场本地 API")
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    args = parser.parse_args()
    settings = replace(defaults, host=args.host, port=args.port)
    serve(MarketService(settings), settings.host, settings.port)


if __name__ == "__main__":
    main()
