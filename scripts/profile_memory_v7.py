from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path


TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
CREATE_NO_WINDOW = 0x08000000


class ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


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


class MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(ProcessEntry32),
]
kernel32.Process32NextW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(ProcessEntry32),
]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(ProcessMemoryCounters),
    wintypes.DWORD,
]
kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatusEx)]


def process_table() -> dict[int, tuple[int, str]]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    entry = ProcessEntry32()
    entry.dwSize = ctypes.sizeof(entry)
    rows: dict[int, tuple[int, str]] = {}
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            rows[int(entry.th32ProcessID)] = (
                int(entry.th32ParentProcessID),
                str(entry.szExeFile).lower(),
            )
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return rows


def descendants(root_pid: int, table: dict[int, tuple[int, str]]) -> set[int]:
    found = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent, _name) in table.items():
            if parent in found and pid not in found:
                found.add(pid)
                changed = True
    return found


def process_rss(pid: int) -> tuple[int, int]:
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid
    )
    if not handle:
        return 0, 0
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    try:
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return 0, 0
        return int(counters.WorkingSetSize), int(counters.PrivateUsage)
    finally:
        kernel32.CloseHandle(handle)


def system_memory() -> dict[str, float]:
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    mb = 1_048_576
    return {
        "system_available_mb": round(status.ullAvailPhys / mb, 1),
        "system_used_mb": round((status.ullTotalPhys - status.ullAvailPhys) / mb, 1),
        "system_pagefile_used_mb": round(
            (status.ullTotalPageFile - status.ullAvailPageFile) / mb, 1
        ),
        "system_memory_load_pct": float(status.dwMemoryLoad),
    }


def wait_url(url: str, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"service did not become ready: {url}")


def terminate_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--app-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stocks", type=int, default=40)
    parser.add_argument("--sample-seconds", type=float, default=0.5)
    parser.add_argument("--frontend-port", type=int, default=13000)
    parser.add_argument("--backend-port", type=int, default=18765)
    args = parser.parse_args()
    app_root = args.app_root.resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    events_path = output.with_suffix(".events.jsonl")
    events_path.write_text("", encoding="utf-8")
    logs = output.parent / f"{args.label}-logs"
    logs.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["MARKET_PORT"] = str(args.backend_port)
    environment["NEXT_PUBLIC_MARKET_API"] = (
        f"http://127.0.0.1:{args.backend_port}/api"
    )
    hidden = {"creationflags": CREATE_NO_WINDOW}
    pnpm = shutil.which("pnpm.cmd") or str(
        Path(
            r"C:\Users\hp\.cache\codex-runtimes\codex-primary-runtime"
            r"\dependencies\bin\fallback\pnpm.cmd"
        )
    )
    node = shutil.which("node.exe") or str(
        Path(
            r"C:\Users\hp\.cache\codex-runtimes\codex-primary-runtime"
            r"\dependencies\node\bin\node.exe"
        )
    )
    subprocess.run(
        [pnpm, "build"],
        cwd=app_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=True,
        **hidden,
    )
    backend_log = (logs / "backend.log").open("w", encoding="utf-8")
    frontend_log = (logs / "frontend.log").open("w", encoding="utf-8")
    driver_log = (logs / "driver.log").open("w", encoding="utf-8")
    backend = subprocess.Popen(
        [
            "uv",
            "run",
            "--project",
            r"C:\Users\hp\Documents\zer0share",
            "python",
            "-m",
            "server",
        ],
        cwd=app_root,
        env=environment,
        stdout=backend_log,
        stderr=subprocess.STDOUT,
        **hidden,
    )
    try:
        frontend = subprocess.Popen(
            [pnpm, "exec", "vinext", "dev", "-p", str(args.frontend_port)],
            cwd=app_root,
            env=environment,
            stdout=frontend_log,
            stderr=subprocess.STDOUT,
            **hidden,
        )
    except Exception:
        terminate_tree(backend)
        backend_log.close()
        frontend_log.close()
        driver_log.close()
        raise
    driver = None
    samples: list[dict[str, object]] = []
    stop = threading.Event()

    def sample_loop() -> None:
        while not stop.is_set():
            table = process_table()
            backend_pids = descendants(backend.pid, table)
            frontend_pids = descendants(frontend.pid, table)
            driver_pids = descendants(driver.pid, table) if driver else set()
            chrome_pids = {
                pid
                for pid in driver_pids
                if "chrome" in table.get(pid, (0, ""))[1]
            }

            def total(pids: set[int], index: int) -> int:
                return sum(process_rss(pid)[index] for pid in pids)

            app_pids = backend_pids | chrome_pids
            host_pids = app_pids | frontend_pids
            mb = 1_048_576
            samples.append(
                {
                    "timestamp_ms": int(time.time() * 1000),
                    "backend_rss_mb": round(total(backend_pids, 0) / mb, 1),
                    "backend_private_mb": round(total(backend_pids, 1) / mb, 1),
                    "chrome_rss_mb": round(total(chrome_pids, 0) / mb, 1),
                    "chrome_private_mb": round(total(chrome_pids, 1) / mb, 1),
                    "frontend_rss_mb": round(total(frontend_pids, 0) / mb, 1),
                    "app_total_rss_mb": round(total(app_pids, 0) / mb, 1),
                    "host_total_including_frontend_rss_mb": round(
                        total(host_pids, 0) / mb, 1
                    ),
                    "chrome_processes": len(chrome_pids),
                    **system_memory(),
                }
            )
            stop.wait(args.sample_seconds)

    try:
        wait_url(f"http://127.0.0.1:{args.backend_port}/api/health")
        wait_url(f"http://localhost:{args.frontend_port}/market")
        driver_env = environment.copy()
        driver_env.update(
            {
                "MEMORY_APP_URL": f"http://localhost:{args.frontend_port}",
                "MEMORY_API_URL": f"http://127.0.0.1:{args.backend_port}/api",
                "MEMORY_EVENTS_PATH": str(events_path),
                "MEMORY_STOCKS": str(args.stocks),
            }
        )
        driver = subprocess.Popen(
            [node, str(Path(__file__).with_suffix(".mjs"))],
            cwd=Path(__file__).resolve().parents[1],
            env=driver_env,
            stdout=driver_log,
            stderr=subprocess.STDOUT,
            **hidden,
        )
        sampler = threading.Thread(target=sample_loop, daemon=True)
        sampler.start()
        exit_code = driver.wait(timeout=1800)
        stop.set()
        sampler.join(timeout=5)
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        result = {
            "label": args.label,
            "app_root": str(app_root),
            "baseline_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=app_root, text=True
            ).strip(),
            "stocks": args.stocks,
            "driver_exit_code": exit_code,
            "events": events,
            "samples": samples,
            "peaks": {
                key: max((float(row[key]) for row in samples), default=0)
                for key in (
                    "backend_rss_mb",
                    "chrome_rss_mb",
                    "frontend_rss_mb",
                    "app_total_rss_mb",
                    "host_total_including_frontend_rss_mb",
                    "system_pagefile_used_mb",
                )
            },
            "minimum_system_available_mb": min(
                (float(row["system_available_mb"]) for row in samples), default=0
            ),
        }
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if exit_code != 0:
            raise RuntimeError(f"browser driver failed; see {logs / 'driver.log'}")
    finally:
        stop.set()
        if driver is not None:
            terminate_tree(driver)
        terminate_tree(frontend)
        terminate_tree(backend)
        backend_log.close()
        frontend_log.close()
        driver_log.close()


if __name__ == "__main__":
    main()
