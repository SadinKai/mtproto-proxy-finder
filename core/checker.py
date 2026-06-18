"""
Core orchestrator for proxy validation, state tracking, and health scoring.
Maintains history in proxy_state.json, manages concurrent execution, and aggregates stats.
"""

import asyncio
import json
import os
import sys
import time
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Any, Tuple, Optional, Callable

from core.mtproto import check_proxy
from exports.exporter import generate_exports

STATE_FILE = "output/proxy_state.json"
ARCHIVE_FILE = "archive/archive_dead.txt"


def is_publish_mode() -> bool:
    """Checks if PUBLISH_MODE is enabled in environment or .env."""
    if os.environ.get("PUBLISH_MODE") is not None:
        return os.environ.get("PUBLISH_MODE", "false").lower() == "true"
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("PUBLISH_MODE="):
                        return line.strip().split("=", 1)[1].strip().lower() == "true"
        except Exception:
            pass
    return False


def load_state() -> Dict[str, Dict[str, Any]]:
    """Loads historical proxy statistics from proxy_state.json."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load state database: {e}")
        return {}


def save_state(state: Dict[str, Dict[str, Any]]):
    """Saves proxy statistics to proxy_state.json."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Error: Failed to save state database: {e}")


def calculate_health_score(success_count: int, failure_count: int, consecutive_failures: int, avg_latency_ms: float) -> int:
    """
    Calculates health score from 0 to 100.
    Prioritizes reliability and consistency over raw speed.
    """
    total_checks = success_count + failure_count
    if total_checks == 0:
        return 100

    # Base score on success rate
    success_rate = (success_count / total_checks) * 100.0

    # Penalty for consecutive failures
    consecutive_penalty = consecutive_failures * 15.0

    # Penalty for high latency (max 20 point penalty for 2000ms+)
    latency_penalty = min(20.0, avg_latency_ms / 100.0)

    score = success_rate - consecutive_penalty - latency_penalty
    return max(0, min(100, int(round(score))))


def update_proxy_state(
    state: Dict[str, Dict[str, Any]],
    url: str,
    success: bool,
    latency_ms: Optional[float]
) -> Tuple[Dict[str, Any], bool]:
    """
    Updates the historical state for a single proxy URL.
    Returns the updated dictionary and a boolean indicating if it has been archived/cleaned up.
    """
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    
    # Initialize state entry if new
    if url not in state:
        state[url] = {
            "success_count": 0,
            "failure_count": 0,
            "consecutive_failures": 0,
            "avg_latency_ms": 0.0,
            "last_seen": "",
            "health_score": 100
        }

    entry = state[url]

    if success:
        entry["success_count"] += 1
        entry["consecutive_failures"] = 0
        entry["last_seen"] = now_str
        
        # Calculate moving average latency
        if latency_ms is not None:
            prev_avg = entry.get("avg_latency_ms", 0.0)
            prev_success = entry["success_count"] - 1
            if prev_success > 0:
                entry["avg_latency_ms"] = ((prev_avg * prev_success) + latency_ms) / entry["success_count"]
            else:
                entry["avg_latency_ms"] = latency_ms
    else:
        entry["failure_count"] += 1
        entry["consecutive_failures"] += 1

    # Update health score
    entry["health_score"] = calculate_health_score(
        entry["success_count"],
        entry["failure_count"],
        entry["consecutive_failures"],
        entry["avg_latency_ms"]
    )

    # Check for cleanup (3 consecutive failures)
    archived = False
    if entry["consecutive_failures"] >= 3:
        archived = True
        try:
            os.makedirs(os.path.dirname(ARCHIVE_FILE), exist_ok=True)
            with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
                f.write(f"{url} # Archived on {now_str} (consecutive failures: {entry['consecutive_failures']})\n")
        except Exception as e:
            print(f"Error writing to archive: {e}")

    return entry, archived


class ScanStats:
    """Tracks running counters for display and final report."""
    def __init__(self, total: int):
        self.total = total
        self.checked = 0
        self.working = 0
        self.dead = 0
        self.fastest_url: Optional[str] = None
        self.fastest_ms: float = 999999.0
        self.total_latency_sum = 0.0
        self.best_health_score = 0

    def add_result(self, url: str, status: str, latency_ms: Optional[float], health_score: int):
        self.checked += 1
        if status == "OK":
            self.working += 1
            if latency_ms is not None:
                self.total_latency_sum += latency_ms
                if latency_ms < self.fastest_ms:
                    self.fastest_ms = latency_ms
                    self.fastest_url = url
            if health_score > self.best_health_score:
                self.best_health_score = health_score
        else:
            self.dead += 1

    def get_success_rate(self) -> float:
        return (self.working / self.checked * 100.0) if self.checked > 0 else 0.0

    def get_average_latency(self) -> float:
        return (self.total_latency_sum / self.working) if self.working > 0 else 0.0


async def check_single_worker(
    sem: asyncio.Semaphore,
    url: str,
    timeout: float,
    state: Dict[str, Dict[str, Any]],
    stats: ScanStats,
    working_list: List[Dict[str, Any]],
    dead_list: List[Dict[str, Any]],
    log_func: Optional[Callable[[str], None]],
    progress_callback: Optional[Callable[[int, int, int, int], None]] = None
):
    """Concurrency worker that checks a proxy and updates history/stats."""
    async with sem:
        try:
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            host = query["server"][0].strip()
            port = int(query["port"][0].strip())
            secret = query["secret"][0].strip()
        except Exception:
            # Mark invalid format as dead
            stats.add_result(url, "INVALID_RESPONSE", None, 0)
            dead_list.append({"url": url, "status": "INVALID_RESPONSE"})
            if progress_callback:
                progress_callback(stats.checked, stats.working, stats.dead, stats.total)
            return

        status, timings = await check_proxy(
            host=host,
            port=port,
            secret_str=secret,
            timeout=timeout,
            dc_id=2
        )

        success = (status == "OK")
        latency_ms = timings["total_ms"] if success and timings else None

        # Update historical state DB and check for 3-strike archival
        entry, archived = update_proxy_state(state, url, success, latency_ms)

        stats.add_result(url, status, latency_ms, entry["health_score"])

        # Display output
        if success and timings:
            msg = f"[OK] {host}:{port} - {timings['total_ms']:.0f}ms (health: {entry['health_score']}%)"
            if log_func:
                log_func(msg)
            
            # Save comprehensive benchmarking record
            working_list.append({
                "url": url,
                "host": host,
                "port": port,
                "total_ms": timings["total_ms"],
                "connect_ms": timings["connect_ms"],
                "handshake_ms": timings["handshake_ms"],
                "resolve_ms": timings["resolve_ms"],
                "health_score": entry["health_score"]
            })
        else:
            msg = f"[{status}] {host}:{port}"
            if log_func:
                log_func(msg)
            
            dead_list.append({
                "url": url,
                "status": status
            })

        # Remove from state dictionary if archived
        if archived:
            if log_func:
                log_func(f"Proxy {host}:{port} failed 3 cycles in a row. Archiving to dead lists.")
            if url in state:
                del state[url]

        if progress_callback:
            progress_callback(stats.checked, stats.working, stats.dead, stats.total)


async def run_validation_flow(
    urls: List[str],
    workers: int,
    timeout: float,
    log_func: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[int, int, int, int], None]] = None
) -> Tuple[ScanStats, List[Dict[str, Any]]]:
    """Runs verification checks concurrently and handles exports/reports."""
    state = load_state()
    stats = ScanStats(len(urls))
    
    working_list: List[Dict[str, Any]] = []
    dead_list: List[Dict[str, Any]] = []

    sem = asyncio.Semaphore(workers)

    if log_func:
        mode_name = "Publish Mode" if is_publish_mode() else "Private Mode"
        log_func(f"Running in {mode_name} (PUBLISH_MODE={str(is_publish_mode()).lower()})")
        log_func(f"Starting verification on {len(urls)} proxies with {workers} concurrent workers...")

    tasks = [
        check_single_worker(
            sem=sem,
            url=url,
            timeout=timeout,
            state=state,
            stats=stats,
            working_list=working_list,
            dead_list=dead_list,
            log_func=log_func,
            progress_callback=progress_callback
        )
        for url in urls
    ]

    await asyncio.gather(*tasks)

    # Save state database
    save_state(state)

    # Generate exported files
    if log_func:
        log_func("Validation completed. Writing exports...")
    generate_exports(stats.checked, working_list, dead_list)

    return stats, working_list
