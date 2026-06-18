"""
Tkinter GUI Application for MTProto Proxy Finder & Manager.
Implements a responsive, dark-themed interface running check sessions asynchronously in a background thread.
"""

import asyncio
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Any, Optional

from core.checker import run_validation_flow, load_state
from scrapers.collector import collect_proxies

# Modern dark theme color tokens
COLOR_BG = "#0f172a"          # Slate 900
COLOR_CARD_BG = "#1e293b"     # Slate 800
COLOR_BORDER = "#334155"      # Slate 700
COLOR_TEXT_PRIMARY = "#f8fafc" # Slate 50
COLOR_TEXT_MUTED = "#94a3b8"  # Slate 400
COLOR_EMERALD = "#10b981"     # Emerald 500
COLOR_ROSE = "#ef4444"        # Rose 500
COLOR_CYAN = "#06b6d4"        # Cyan 500
COLOR_INDIGO = "#6366f1"      # Indigo 500
COLOR_INDIGO_HOVER = "#4f46e5"


class AsyncLoopThread(threading.Thread):
    """Background thread running an asyncio event loop to prevent UI locking."""
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()


class GUIApplication:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("MTProto Proxy Finder & Manager")
        self.root.geometry("1200x800")
        self.root.configure(bg=COLOR_BG)

        # Start background asyncio thread
        self.loop_thread = AsyncLoopThread()
        self.loop_thread.start()

        # Variables
        self.workers_var = tk.IntVar(value=100)
        self.timeout_var = tk.DoubleVar(value=5.0)
        self.is_running = False
        self.current_task: Optional[asyncio.Future] = None
        self.scraped_urls: List[str] = []

        # Configure styles
        self.setup_styles()

        # Build UI layout
        self.build_ui()

        # Load existing state if available to populate table initially
        self.populate_from_saved_state()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # General frame/label styling
        style.configure("TFrame", background=COLOR_BG)
        style.configure("Card.TFrame", background=COLOR_CARD_BG, borderwidth=1, relief="solid")
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT_PRIMARY, font=("Plus Jakarta Sans", 10))
        style.configure("Muted.TLabel", background=COLOR_BG, foreground=COLOR_TEXT_MUTED, font=("Plus Jakarta Sans", 9))
        
        # Stats styling
        style.configure("StatLabel.TLabel", background=COLOR_CARD_BG, foreground=COLOR_TEXT_MUTED, font=("Plus Jakarta Sans", 9, "bold"))
        style.configure("StatVal.TLabel", background=COLOR_CARD_BG, foreground=COLOR_TEXT_PRIMARY, font=("JetBrains Mono", 20, "bold"))

        # Input fields
        style.configure("TSpinbox", fieldbackground=COLOR_CARD_BG, background=COLOR_CARD_BG, foreground=COLOR_TEXT_PRIMARY, bordercolor=COLOR_BORDER)
        
        # Notebook styling
        style.configure("TNotebook", background=COLOR_BG, bordercolor=COLOR_BORDER)
        style.configure("TNotebook.Tab", background=COLOR_CARD_BG, foreground=COLOR_TEXT_MUTED, bordercolor=COLOR_BORDER, padding=(12, 4))
        style.map("TNotebook.Tab", background=[("selected", COLOR_BG)], foreground=[("selected", COLOR_TEXT_PRIMARY)])

        # Treeview styled table
        style.configure("Treeview",
            background=COLOR_CARD_BG,
            fieldbackground=COLOR_CARD_BG,
            foreground=COLOR_TEXT_PRIMARY,
            rowheight=30,
            borderwidth=0,
            font=("Plus Jakarta Sans", 10)
        )
        style.map("Treeview", background=[("selected", COLOR_INDIGO)], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading",
            background=COLOR_BG,
            foreground=COLOR_TEXT_PRIMARY,
            borderwidth=1,
            relief="solid",
            font=("Plus Jakarta Sans", 9, "bold")
        )
        style.map("Treeview.Heading", background=[("active", COLOR_CARD_BG)])

        # Progress bar
        style.configure("TProgressbar", thickness=8, troughcolor=COLOR_CARD_BG, background=COLOR_EMERALD)

    def build_ui(self):
        # 1. Main Grid Layout Configuration
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)  # Expandable row for central layouts

        # --- Top Menu/Control Bar ---
        top_bar = ttk.Frame(self.root, padding=15)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.columnconfigure(2, weight=1)

        # Control fields
        ttk.Label(top_bar, text="Workers:").grid(row=0, column=0, padx=(0, 5))
        self.workers_spin = ttk.Spinbox(top_bar, from_=1, to=500, width=5, textvariable=self.workers_var)
        self.workers_spin.grid(row=0, column=1, padx=(0, 15))

        ttk.Label(top_bar, text="Timeout (s):").grid(row=0, column=2, padx=(0, 5), sticky="w")
        self.timeout_spin = ttk.Spinbox(top_bar, from_=1.0, to=30.0, increment=1.0, width=5, textvariable=self.timeout_var)
        self.timeout_spin.grid(row=0, column=2, padx=(85, 0), sticky="w")

        # Buttons
        self.btn_scan = tk.Button(top_bar, text="Start Scan", bg=COLOR_INDIGO, fg="#ffffff", activebackground=COLOR_INDIGO_HOVER, activeforeground="#ffffff", font=("Plus Jakarta Sans", 10, "bold"), relief="flat", padx=12, pady=4, command=self.on_scan_clicked)
        self.btn_scan.grid(row=0, column=3, padx=(0, 10))

        self.btn_update = tk.Button(top_bar, text="Update (Scrape & Check)", bg=COLOR_EMERALD, fg="#ffffff", activebackground=COLOR_EMERALD, activeforeground="#ffffff", font=("Plus Jakarta Sans", 10, "bold"), relief="flat", padx=12, pady=4, command=self.on_update_clicked)
        self.btn_update.grid(row=0, column=4, padx=(0, 10))

        self.btn_export = tk.Button(top_bar, text="Export Files", bg=COLOR_CARD_BG, fg=COLOR_TEXT_PRIMARY, activebackground=COLOR_CARD_BG, font=("Plus Jakarta Sans", 10), relief="groove", padx=12, pady=4, command=self.on_export_clicked)
        self.btn_export.grid(row=0, column=5, padx=(0, 10))

        self.btn_best = tk.Button(top_bar, text="Open Best Proxy", bg=COLOR_CARD_BG, fg=COLOR_TEXT_PRIMARY, activebackground=COLOR_CARD_BG, font=("Plus Jakarta Sans", 10), relief="groove", padx=12, pady=4, command=self.on_open_best_clicked)
        self.btn_best.grid(row=0, column=6)

        # --- Dashboard/Stats Bar ---
        stats_frame = ttk.Frame(self.root, padding=(15, 0, 15, 15))
        stats_frame.grid(row=1, column=0, sticky="ew")
        for i in range(6):
            stats_frame.columnconfigure(i, weight=1)

        self.stat_total = self.create_stat_card(stats_frame, 0, "TOTAL CHECKED", "0")
        self.stat_working = self.create_stat_card(stats_frame, 1, "WORKING / ACTIVE", "0", COLOR_EMERALD)
        self.stat_dead = self.create_stat_card(stats_frame, 2, "DEAD / INACTIVE", "0", COLOR_ROSE)
        self.stat_rate = self.create_stat_card(stats_frame, 3, "SUCCESS RATE", "0.0%")
        self.stat_latency = self.create_stat_card(stats_frame, 4, "AVERAGE LATENCY", "0 ms")
        self.stat_best_health = self.create_stat_card(stats_frame, 5, "BEST HEALTH SCORE", "0%")

        # --- Central Split Panel (Tables on Left, Logs on Right) ---
        main_panel = ttk.Frame(self.root, padding=(15, 0, 15, 15))
        main_panel.grid(row=2, column=0, sticky="nsew")
        self.root.rowconfigure(2, weight=1)
        main_panel.columnconfigure(0, weight=2)  # Tables take more width
        main_panel.columnconfigure(1, weight=1)  # Logs take less width

        # Left: Notebook with tabs for Working and Dead proxies
        notebook = ttk.Notebook(main_panel)
        notebook.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Working proxies tab
        working_frame = ttk.Frame(notebook)
        notebook.add(working_frame, text="Working Proxies")
        self.setup_working_table(working_frame)

        # Dead proxies tab
        dead_frame = ttk.Frame(notebook)
        notebook.add(dead_frame, text="Dead Proxies")
        self.setup_dead_table(dead_frame)

        # Right: Live Logs Text Area
        log_frame = ttk.Frame(main_panel)
        log_frame.grid(row=0, column=1, sticky="nsew")
        log_frame.rowconfigure(1, weight=1)
        log_frame.columnconfigure(0, weight=1)

        ttk.Label(log_frame, text="Live Output Logs:", font=("Plus Jakarta Sans", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 5))
        
        self.log_text = tk.Text(log_frame, bg="#020617", fg=COLOR_TEXT_PRIMARY, font=("JetBrains Mono", 9), wrap="word", borderwidth=1, relief="solid")
        self.log_text.grid(row=1, column=0, sticky="nsew")
        
        # Add scrollbar for logs
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        # --- Bottom Status bar with Progress ---
        bottom_bar = ttk.Frame(self.root, padding=(15, 5, 15, 15))
        bottom_bar.grid(row=3, column=0, sticky="ew")
        bottom_bar.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(bottom_bar, orient="horizontal", mode="determinate")
        self.progress_bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        self.lbl_status = ttk.Label(bottom_bar, text="Ready", style="Muted.TLabel")
        self.lbl_status.grid(row=1, column=0, sticky="w")

    def create_stat_card(self, parent, col: int, label: str, value: str, accent_color: str = None) -> ttk.Label:
        """Helper to create a beautiful flat dashboard card."""
        card = ttk.Frame(parent, style="Card.TFrame", padding=10)
        card.grid(row=0, column=col, padx=(0 if col == 0 else 10, 0), sticky="ew")
        
        lbl = ttk.Label(card, text=label, style="StatLabel.TLabel")
        lbl.pack(anchor="w")
        
        val_lbl = ttk.Label(card, text=value, style="StatVal.TLabel")
        if accent_color:
            val_lbl.configure(foreground=accent_color)
        val_lbl.pack(anchor="w", pady=(5, 0))
        return val_lbl

    def setup_working_table(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        columns = ("rank", "server", "type", "health", "latency", "connect", "handshake")
        self.working_tree = ttk.Treeview(parent, columns=columns, show="headings")
        self.working_tree.grid(row=0, column=0, sticky="nsew")

        # Define headings and column layouts
        headings = {
            "rank": ("Rank", 50),
            "server": ("Server Address", 250),
            "type": ("Type", 80),
            "health": ("Health Score", 100),
            "latency": ("Total RTT", 100),
            "connect": ("TCP Connect", 100),
            "handshake": ("Handshake RTT", 110)
        }

        for col, (text, width) in headings.items():
            self.working_tree.heading(col, text=text, command=lambda c=col: self.sort_column(self.working_tree, c, False))
            self.working_tree.column(col, width=width, anchor="center" if col != "server" else "w")

        # Scrollbar
        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.working_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.working_tree.configure(yscrollcommand=scroll.set)

        # Bindings: Double click copies full proxy URL
        self.working_tree.bind("<Double-1>", lambda e: self.on_row_double_click(self.working_tree))

    def setup_dead_table(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        columns = ("server", "reason")
        self.dead_tree = ttk.Treeview(parent, columns=columns, show="headings")
        self.dead_tree.grid(row=0, column=0, sticky="nsew")

        self.dead_tree.heading("server", text="Server Address", command=lambda: self.sort_column(self.dead_tree, "server", False))
        self.dead_tree.heading("reason", text="Status Code / Reason", command=lambda: self.sort_column(self.dead_tree, "reason", False))
        
        self.dead_tree.column("server", width=350, anchor="w")
        self.dead_tree.column("reason", width=250, anchor="center")

        # Scrollbar
        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.dead_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.dead_tree.configure(yscrollcommand=scroll.set)

        # Bindings
        self.dead_tree.bind("<Double-1>", lambda e: self.on_row_double_click(self.dead_tree))

    def sort_column(self, tree, col, reverse):
        """Sorts Treeview columns. Supports numerical sorting for latency/scores."""
        l = [(tree.set(k, col), k) for k in tree.get_children("")]
        
        if col in ("latency", "health", "connect", "handshake", "rank"):
            def parse_val(val_str):
                val_str = val_str.replace(" ms", "").replace("%", "").replace("#", "")
                try:
                    return float(val_str)
                except ValueError:
                    return 999999.0 if col in ("latency", "connect", "handshake") else -1.0
            l.sort(key=lambda t: parse_val(t[0]), reverse=reverse)
        else:
            l.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for index, (val, k) in enumerate(l):
            tree.move(k, "", index)

        # Reset heading command to invert order on subsequent clicks
        tree.heading(col, command=lambda: self.sort_column(tree, col, not reverse))

    def log(self, message: str):
        """Writes logs to the UI text display (thread-safe scheduler)."""
        self.root.after(0, self._sync_log, message)

    def _sync_log(self, message: str):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def update_status(self, text: str):
        self.root.after(0, lambda: self.lbl_status.configure(text=text))

    def update_progress_callback(self, checked: int, working: int, dead: int, total: int):
        """Called by checker core to update UI values incrementally."""
        self.root.after(0, self._sync_progress, checked, working, dead, total)

    def _sync_progress(self, checked: int, working: int, dead: int, total: int):
        self.stat_total.configure(text=str(checked))
        self.stat_working.configure(text=str(working))
        self.stat_dead.configure(text=str(dead))
        
        rate = (working / checked * 100.0) if checked > 0 else 0.0
        self.stat_rate.configure(text=f"{rate:.1f}%")

        if total > 0:
            pct = (checked / total) * 100
            self.progress_bar["value"] = pct
            self.update_status(f"Checked {checked}/{total} proxies...")

    def populate_from_saved_state(self):
        """Reads proxy_state.json and populates working/dead tables on launch."""
        state = load_state()
        if not state:
            return
        
        self.working_tree.delete(*self.working_tree.get_children())
        
        # Populate working items (health > 0)
        working_items = []
        for url, data in state.items():
            if data.get("health_score", 0) > 0:
                try:
                    parsed = urlparse(url)
                    query = parse_qs(parsed.query)
                    host = query["server"][0].strip()
                    port = query["port"][0].strip()
                    secret = query["secret"][0].strip()
                    ptype = "FakeTLS" if secret.startswith("ee") else "Padded" if secret.startswith("dd") else "Plain"
                except Exception:
                    continue

                working_items.append({
                    "url": url,
                    "server": f"{host}:{port}",
                    "type": ptype,
                    "health": data.get("health_score", 0),
                    "latency": data.get("avg_latency_ms", 999999.0)
                })

        # Sort working by health, then latency
        working_items.sort(key=lambda x: (-x["health"], x["latency"]))

        for idx, item in enumerate(working_items):
            self.working_tree.insert(
                "",
                "end",
                values=(
                    f"#{idx+1}",
                    item["server"],
                    item["type"],
                    f"{item['health']}%",
                    f"{item['latency']:.0f} ms",
                    "N/A",
                    "N/A"
                ),
                tags=(item["url"],)
            )

        self.stat_total.configure(text=str(len(state)))
        self.stat_working.configure(text=str(len(working_items)))
        self.stat_dead.configure(text=str(len(state) - len(working_items)))

    # --- Button actions ---
    def on_scan_clicked(self):
        if self.is_running:
            self.stop_current_scan()
            return

        # Let user select file or scan proxies.txt
        file_path = filedialog.askopenfilename(
            title="Select Proxy File",
            initialdir=".",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not file_path:
            return

        self.is_running = True
        self.btn_scan.configure(text="Stop Scan", bg=COLOR_ROSE)
        self.btn_update.configure(state="disabled")
        self.log_text.delete(1.0, tk.END)

        # Submit tasks
        self.current_task = asyncio.run_coroutine_threadsafe(
            self.run_verification_file(file_path),
            self.loop_thread.loop
        )

    def on_update_clicked(self):
        if self.is_running:
            self.stop_current_scan()
            return

        self.is_running = True
        self.btn_scan.configure(state="disabled")
        self.btn_update.configure(text="Stop Scan", bg=COLOR_ROSE)
        self.log_text.delete(1.0, tk.END)

        self.current_task = asyncio.run_coroutine_threadsafe(
            self.run_update_flow(),
            self.loop_thread.loop
        )

    def stop_current_scan(self):
        if self.current_task:
            self.current_task.cancel()
        self.is_running = False
        self.update_status("Scan cancelled by user.")
        self.reset_control_buttons()

    def reset_control_buttons(self):
        self.btn_scan.configure(text="Start Scan", bg=COLOR_INDIGO, state="normal")
        self.btn_update.configure(text="Update (Scrape & Check)", bg=COLOR_EMERALD, state="normal")

    async def run_verification_file(self, file_path: str):
        try:
            self.log(f"Reading proxies from: {file_path}")
            urls = []
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Attempt to extract
                        from scrapers.collector import normalize_proxy_url
                        normalized = normalize_proxy_url(line)
                        if normalized:
                            urls.append(normalized)
            
            if not urls:
                self.log("No valid proxy URLs found in selected file.")
                self.root.after(0, lambda: messagebox.showwarning("Warning", "No valid proxy URLs found in file."))
                self.root.after(0, self.reset_control_buttons)
                return

            self.root.after(0, lambda: self.progress_bar.configure(maximum=100, value=0))
            
            stats, working_list = await run_validation_flow(
                urls=urls,
                workers=self.workers_var.get(),
                timeout=self.timeout_var.get(),
                log_func=self.log,
                progress_callback=self.update_progress_callback
            )

            # Sync tables and final stats
            self.root.after(0, self.sync_results_to_ui, working_list, stats)

        except asyncio.CancelledError:
            self.log("\nScan cancelled.")
        except Exception as e:
            self.log(f"\nError: {e}")
        finally:
            self.is_running = False
            self.root.after(0, self.reset_control_buttons)

    async def run_update_flow(self):
        try:
            self.log("Initializing Auto Discovery and Update Mode...")
            
            # 1. Scrape proxies
            self.update_status("Scraping fresh public proxies...")
            scraped = await collect_proxies(log_func=self.log)
            
            # 2. Merge with existing proxies.txt
            existing_urls = []
            if os.path.exists("proxies.txt"):
                with open("proxies.txt", "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            from scrapers.collector import normalize_proxy_url
                            normalized = normalize_proxy_url(line)
                            if normalized:
                                existing_urls.append(normalized)

            all_urls = sorted(list(set(scraped + existing_urls)))
            self.log(f"Merged proxies.txt. Total unique candidates to test: {len(all_urls)}")
            
            # Write unique candidates to proxies.txt
            with open("proxies.txt", "w", encoding="utf-8") as f:
                for url in all_urls:
                    f.write(f"{url}\n")

            if not all_urls:
                self.log("No proxies collected.")
                self.root.after(0, self.reset_control_buttons)
                return

            self.root.after(0, lambda: self.progress_bar.configure(maximum=100, value=0))

            # 3. Validate
            stats, working_list = await run_validation_flow(
                urls=all_urls,
                workers=self.workers_var.get(),
                timeout=self.timeout_var.get(),
                log_func=self.log,
                progress_callback=self.update_progress_callback
            )

            # 4. Sync UI tables and stats
            self.root.after(0, self.sync_results_to_ui, working_list, stats)
            self.log("\nUpdate cycle finished. All exports updated successfully.")

        except asyncio.CancelledError:
            self.log("\nScan cancelled.")
        except Exception as e:
            self.log(f"\nError: {e}")
        finally:
            self.is_running = False
            self.root.after(0, self.reset_control_buttons)

    def sync_results_to_ui(self, working_list: List[Dict[str, Any]], stats):
        """Refreshes Treeview lists with the tested output details."""
        self.working_tree.delete(*self.working_tree.get_children())
        self.dead_tree.delete(*self.dead_tree.get_children())

        # Sort working list by health descending, total_ms ascending
        working_sorted = sorted(
            working_list,
            key=lambda x: (-x.get("health_score", 0), x.get("total_ms", 999999))
        )

        for idx, item in enumerate(working_sorted):
            try:
                parsed = urlparse(item["url"])
                secret = parse_qs(parsed.query)["secret"][0].strip()
                ptype = "FakeTLS" if secret.startswith("ee") else "Padded" if secret.startswith("dd") else "Plain"
            except Exception:
                ptype = "Plain"

            self.working_tree.insert(
                "",
                "end",
                values=(
                    f"#{idx+1}",
                    f"{item['host']}:{item['port']}",
                    ptype,
                    f"{item['health_score']}%",
                    f"{item['total_ms']:.0f} ms",
                    f"{item['connect_ms']:.0f} ms",
                    f"{item['handshake_ms']:.0f} ms"
                ),
                tags=(item["url"],)
            )

        # Reload dead proxies from files or state
        state = load_state()
        dead_count = 0
        for url, data in state.items():
            if data.get("health_score", 0) == 0:
                try:
                    parsed = urlparse(url)
                    query = parse_qs(parsed.query)
                    host = query["server"][0].strip()
                    port = query["port"][0].strip()
                except Exception:
                    continue
                self.dead_tree.insert("", "end", values=(f"{host}:{port}", "Offline / Low Health"))
                dead_count += 1

        # Finalize Dashboard stats display
        self.stat_total.configure(text=str(stats.checked))
        self.stat_working.configure(text=str(len(working_sorted)))
        self.stat_dead.configure(text=str(dead_count))
        self.stat_rate.configure(text=f"{stats.get_success_rate():.1f}%")
        self.stat_latency.configure(text=f"{stats.get_average_latency():.0f} ms")
        self.stat_best_health.configure(text=f"{stats.best_health_score}%")
        
        self.update_status(f"Scan complete. Working: {len(working_sorted)}, Dead: {dead_count}")
        self.progress_bar["value"] = 100

    def on_row_double_click(self, tree):
        item = tree.selection()
        if item:
            # Get tags which store the full URL
            tags = tree.item(item[0], "tags")
            if tags:
                url = tags[0]
                self.root.clipboard_clear()
                self.root.clipboard_append(url)
                self.root.update()
                messagebox.showinfo("Clipboard", "Telegram proxy URL copied to clipboard!")

    def on_export_clicked(self):
        """Manual triggering of file outputs using currently verified database state."""
        state = load_state()
        if not state:
            messagebox.showwarning("Warning", "No state information loaded to export.")
            return

        # Gather working and dead lists
        working_list = []
        dead_list = []
        checked = 0

        for url, data in state.items():
            checked += 1
            try:
                parsed = urlparse(url)
                query = parse_qs(parsed.query)
                host = query["server"][0].strip()
                port = int(query["port"][0].strip())
            except Exception:
                continue

            health = data.get("health_score", 0)
            if health > 0:
                working_list.append({
                    "url": url,
                    "host": host,
                    "port": port,
                    "total_ms": data.get("avg_latency_ms", 120.0),
                    "connect_ms": data.get("avg_latency_ms", 120.0) * 0.4,
                    "handshake_ms": data.get("avg_latency_ms", 120.0) * 0.6,
                    "resolve_ms": 15.0,
                    "health_score": health
                })
            else:
                dead_list.append({
                    "url": url,
                    "status": "DEAD"
                })

        from exports.exporter import generate_exports
        generate_exports(checked, working_list, dead_list)
        messagebox.showinfo("Export", "All files and dashboard.html successfully exported!")

    def on_open_best_clicked(self):
        best_file = "output/best_proxy.txt"
        if not os.path.exists(best_file):
            messagebox.showwarning("Error", "best_proxy.txt does not exist yet. Please run a scan first.")
            return
        
        try:
            # Reads and displays best proxy URL
            with open(best_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                # Copy to clipboard too
                self.root.clipboard_clear()
                self.root.clipboard_append(content)
                self.root.update()
                messagebox.showinfo("Best Proxy", f"Best Proxy:\n\n{content}\n\n(Copied to clipboard)")
            else:
                messagebox.showinfo("Best Proxy", "No working proxies verified yet.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read best_proxy.txt: {e}")
