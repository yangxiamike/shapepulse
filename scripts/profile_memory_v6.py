from __future__ import annotations

import argparse
import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from server.service import MarketService


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def memory() -> dict[str, float]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    ok = psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "rss_mb": round(counters.WorkingSetSize / 1_048_576, 1),
        "peak_rss_mb": round(counters.PeakWorkingSetSize / 1_048_576, 1),
        "private_mb": round(counters.PrivateUsage / 1_048_576, 1),
    }


def cache_counts(service: MarketService) -> dict[str, int]:
    repository = service.repository.cache_info()
    return {
        "metadata": int(repository["metadata"]["entries"]),
        "stock_frames": int(repository["stock_frames"]["entries"]),
        "bars": int(repository["bars"]["entries"]),
        "bars_evictions": int(repository["bars"]["evictions"]),
        "screen_cache": len(service._screen_cache),
        "completed_screens": len(service._completed_screens),
        "industry_result_cache": len(service._industry_strength_cache),
        "industry_input_cache": len(service._industry_strength_input_cache),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stocks", type=int, default=40)
    parser.add_argument("--history-limit", type=int, default=10_000)
    args = parser.parse_args()

    service = MarketService()
    result: dict[str, object] = {
        "stocks": args.stocks,
        "history_limit": args.history_limit,
        "stages": [{"name": "init", **memory(), **cache_counts(service)}],
    }
    screen = service.screen({"top_k": max(50, args.stocks), "mode": "combined"}, False)
    result["stages"].append(
        {
            "name": "screen",
            **memory(),
            **cache_counts(service),
            "elapsed_ms": screen.get("elapsed_ms"),
        }
    )
    codes = list(
        dict.fromkeys(
            item["ts_code"]
            for item in screen.get("results", [])
            if item.get("ts_code")
        )
    )
    if len(codes) < args.stocks:
        for code in service.repository.basic()["ts_code"].astype(str):
            if code not in codes:
                codes.append(code)
            if len(codes) >= args.stocks:
                break
    checkpoints = {1, 10, 20, 30, args.stocks}
    for index, code in enumerate(codes[: args.stocks], 1):
        service.stock(code)
        payload = service.bars(
            code, None, None, "qfq", "1d", args.history_limit
        )
        if index in checkpoints:
            result["stages"].append(
                {
                    "name": f"view_{index}",
                    **memory(),
                    **cache_counts(service),
                    "last_bars": len(payload["bars"]),
                }
            )
    industry = service.industry_strength("breakout")
    result["stages"].append(
        {
            "name": "industry_strength",
            **memory(),
            **cache_counts(service),
            "elapsed_ms": industry.get("timings", {}).get("total_ms"),
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
