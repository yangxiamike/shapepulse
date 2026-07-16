from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZER0SHARE_ROOT = Path(r"C:\Users\hp\Documents\zer0share")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    zer0share_root: Path
    zer0share_config: Path
    thresholds_path: Path
    state_db: Path
    host: str
    port: int


def load_settings() -> Settings:
    root = Path(os.environ.get("ZER0SHARE_ROOT", DEFAULT_ZER0SHARE_ROOT)).resolve()
    config_path = Path(
        os.environ.get("ZER0SHARE_CONFIG", root / "config" / "settings.toml")
    ).resolve()
    thresholds = Path(
        os.environ.get("MARKET_THRESHOLDS", PROJECT_ROOT / "config" / "thresholds.json")
    ).resolve()
    state_db = Path(
        os.environ.get("MARKET_STATE_DB", PROJECT_ROOT / "server" / "market_state.sqlite3")
    ).resolve()
    return Settings(
        project_root=PROJECT_ROOT,
        zer0share_root=root,
        zer0share_config=config_path,
        thresholds_path=thresholds,
        state_db=state_db,
        host=os.environ.get("MARKET_HOST", "127.0.0.1"),
        port=int(os.environ.get("MARKET_PORT", "8765")),
    )


def load_thresholds(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    required = {"screen", "breakout", "pullback", "range_bounce"}
    missing = required.difference(payload)
    if missing:
        raise ValueError(f"threshold config is missing sections: {', '.join(sorted(missing))}")
    return payload
