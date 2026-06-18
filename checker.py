#!/usr/bin/env python3
"""
MTProto Proxy Finder & Manager - Main Entry Point.
Directs command-line operations (validation, automatic update scraping)
or launches the Tkinter GUI application.
"""

import argparse
import asyncio
import os
import sys
import time
from urllib.parse import urlparse, parse_qs

# Ensure current directory is in search path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.checker import run_validation_flow, load_state
from scrapers.collector import collect_proxies, normalize_proxy_url
from exports.exporter import generate_exports

# Terminal color tokens
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_cli_log(msg: str):
    """Simple styled logger for the CLI."""
    now_str = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{CYAN}{now_str}{RESET}] {msg}")


async def execute_update_mode(workers: int, timeout: float):
    """
    Executes the --update mode workflow:
    1. Scrapes fresh proxies from all public sources.
    2. Merges with existing proxies.txt.
    3. De-duplicates and validates all entries.
    4. Automatically updates states, health scores, and exports.
    """
    print_cli_log(f"{BOLD}Starting Auto-Update & Discovery Mode...{RESET}")
    
    # 1. Scrape
    scraped_urls = await collect_proxies(log_func=print_cli_log)
    print_cli_log(f"Scraped {BOLD}{len(scraped_urls)}{RESET} unique candidates from public repositories.")

    # 2. Merge with existing proxies.txt
    existing_urls = []
    if os.path.exists("proxies.txt"):
        try:
            with open("proxies.txt", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        normalized = normalize_proxy_url(line)
                        if normalized:
                            existing_urls.append(normalized)
            print_cli_log(f"Loaded {len(existing_urls)} existing proxies from local proxies.txt.")
        except Exception as e:
            print_cli_log(f"Warning: Failed to read proxies.txt: {e}")

    all_urls = sorted(list(set(scraped_urls + existing_urls)))
    print_cli_log(f"Merged search list contains {BOLD}{len(all_urls)}{RESET} total unique candidate URLs.")

    # Write merged candidates list back to proxies.txt
    try:
        with open("proxies.txt", "w", encoding="utf-8") as f:
            for url in all_urls:
                f.write(f"{url}\n")
    except Exception as e:
        print_cli_log(f"Error saving updated proxies.txt list: {e}")

    if not all_urls:
        print_cli_log("No proxy URLs collected. Exiting.")
        return

    # 3. Validate
    stats, working_list = await run_validation_flow(
        urls=all_urls,
        workers=workers,
        timeout=timeout,
        log_func=print_cli_log
    )

    # 4. Display Summary statistics
    success_rate = stats.get_success_rate()
    avg_latency = stats.get_average_latency()

    print(f"\n{BOLD}=== Auto-Update Execution Summary ==={RESET}")
    print(f"Total checked: {stats.checked}")
    print(f"Working      : {GREEN}{stats.working}{RESET}")
    print(f"Failed       : {RED}{stats.dead}{RESET}")
    print(f"Success Rate : {CYAN}{success_rate:.1f}%{RESET}")
    print(f"Average RTT  : {CYAN}{avg_latency:.0f} ms{RESET}")
    if stats.fastest_url:
        try:
            parsed = urlparse(stats.fastest_url)
            host = parse_qs(parsed.query)["server"][0].strip()
        except Exception:
            host = stats.fastest_url[:40]
        print(f"Fastest      : {GREEN}{host} ({stats.fastest_ms:.0f} ms){RESET}")
    print(f"Best Health  : {CYAN}Score {stats.best_health_score}{RESET}")
    print(f"All exports and dashboard.html successfully updated.")


async def execute_file_scan(target_path: str, workers: int, timeout: float):
    """CLI handler to scan a custom local file containing proxy URLs."""
    print_cli_log(f"Reading custom target list: {target_path}")
    urls = []
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        normalized = normalize_proxy_url(line)
                        if normalized:
                            urls.append(normalized)
        except Exception as e:
            print(f"Error reading file: {e}")
            sys.exit(1)
    else:
        # Check if argument is a direct single URL
        normalized = normalize_proxy_url(target_path)
        if normalized:
            urls.append(normalized)
        else:
            print(f"Error: Path '{target_path}' is not a valid file or MTProto proxy URL.")
            sys.exit(1)

    if not urls:
        print_cli_log("No valid MTProto URLs parsed. Exiting.")
        sys.exit(0)

    # Validate
    stats, working_list = await run_validation_flow(
        urls=urls,
        workers=workers,
        timeout=timeout,
        log_func=print_cli_log
    )

    # Summary
    success_rate = stats.get_success_rate()
    print(f"\n{BOLD}=== Scan Summary ==={RESET}")
    print(f"Total checked: {stats.checked}")
    print(f"Working      : {GREEN}{stats.working}{RESET}")
    print(f"Failed       : {RED}{stats.dead}{RESET}")
    print(f"Success Rate : {success_rate:.1f}%")
    print(f"All listings updated in active databases.")


def launch_gui_app():
    """Initializes and displays the Tkinter GUI frame."""
    try:
        import tkinter as tk
        from gui.app import GUIApplication
    except ImportError as e:
        print(f"Error: Failed to import GUI components: {e}")
        print("Please ensure Tkinter is installed on your system.")
        sys.exit(1)

    root = tk.Tk()
    app = GUIApplication(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nGUI exited via terminal signal.")


def main():
    parser = argparse.ArgumentParser(
        description="Self-updating Telegram MTProto proxy validation, tracking, and export platform.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Path to a text file containing proxy URLs OR a single proxy URL string. If empty, launches GUI."
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Scrape fresh public proxies, merge, check all, and update databases/exports."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=100,
        help="Maximum concurrent connection checks (default: 100)."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Network timeout in seconds per proxy (default: 5.0)."
    )

    args = parser.parse_args()

    # Determine command path
    if args.update:
        # Run update flow
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        try:
            asyncio.run(execute_update_mode(args.workers, args.timeout))
        except KeyboardInterrupt:
            print("\nAuto-Update canceled by user.")
    elif args.target:
        # Run custom file scan
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        try:
            asyncio.run(execute_file_scan(args.target, args.workers, args.timeout))
        except KeyboardInterrupt:
            print("\nScan canceled by user.")
    else:
        # Default action: Launch GUI
        print_cli_log("No targets supplied. Launching MTProto Proxy Manager GUI...")
        launch_gui_app()


if __name__ == "__main__":
    main()
