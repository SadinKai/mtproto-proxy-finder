"""
Export module for the MTProto Proxy Finder & Manager.
Generates sorted text files, JSON databases, a modern dashboard,
and a Chart.js historical analytics page.
"""

import json
import os
import time
from typing import List, Dict, Any, Tuple
from urllib.parse import urlparse, parse_qs


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


def get_proxy_type(secret_str: str) -> str:
    """Helper to detect proxy secret type for exports."""
    clean_secret = secret_str.strip()
    if clean_secret.startswith("ee") or len(clean_secret) > 34:
        return "FakeTLS"
    elif clean_secret.startswith("dd") and len(clean_secret) == 34:
        return "Padded"
    else:
        return "Plain"


def get_historical_summary_text() -> str:
    """
    Loads history data and computes moving averages to determine the ecosystem trend.
    Returns a formatted summary string.
    """
    history_file = "output/history.json"
    if not os.path.exists(history_file):
        return "Ecosystem trend status is pending more validation cycles."

    try:
        with open(history_file, "r", encoding="utf-8") as f:
            history_data = json.load(f)
    except Exception:
        return "Ecosystem trend status is pending more validation cycles."

    if not history_data or len(history_data) < 2:
        return "Ecosystem trend status is stable based on initial observations."

    # Group by date to get calendar day snapshots
    daily_snapshots = {}
    for entry in history_data:
        date_str = entry.get("timestamp", "2026-06-18")[:10]
        daily_snapshots[date_str] = entry

    sorted_dates = sorted(daily_snapshots.keys())
    daily_entries = [daily_snapshots[d] for d in sorted_dates]

    latest = daily_entries[-1]
    prev_entries = daily_entries[:-1]
    recent_7 = prev_entries[-7:] if len(prev_entries) >= 7 else prev_entries

    if not recent_7:
        return "Ecosystem trend status is stable based on initial observations."

    avg_success_7 = sum(e["success_rate"] for e in recent_7) / len(recent_7)
    avg_latency_7 = sum(e["average_latency_ms"] for e in recent_7) / len(recent_7)

    success_diff = latest["success_rate"] - avg_success_7
    latency_diff = latest["average_latency_ms"] - avg_latency_7

    success_trend = "stable"
    if success_diff > 2.0:
        success_trend = "improving"
    elif success_diff < -2.0:
        success_trend = "declining"

    latency_trend = "stable"
    if latency_diff < -15.0:
        latency_trend = "improving"  # Lower latency is better
    elif latency_diff > 15.0:
        latency_trend = "declining"

    if success_trend == "improving" or latency_trend == "improving":
        if success_trend != "declining" and latency_trend != "declining":
            overall = "improving"
        else:
            overall = "stable"
    elif success_trend == "declining" or latency_trend == "declining":
        overall = "declining"
    else:
        overall = "stable"

    return f"The MTProto ecosystem appears to be {overall} based on historical observations."


def update_history(
    checked_count: int,
    working_list: List[Dict[str, Any]],
    dead_list: List[Dict[str, Any]],
    source_count: int = 7
):
    """
    Appends a new performance snapshot to history.json.
    Does NOT overwrite the current day; every run appends a new snapshot.
    """
    history_file = "output/history.json"
    working_count = len(working_list)
    dead_count = len(dead_list)
    success_rate = round((working_count / checked_count * 100.0) if checked_count > 0 else 0.0, 1)

    latencies = [item["total_ms"] for item in working_list if "total_ms" in item]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    # Calculate median latency
    if latencies:
        sorted_l = sorted(latencies)
        n = len(sorted_l)
        if n % 2 == 1:
            median_latency = sorted_l[n // 2]
        else:
            median_latency = (sorted_l[n // 2 - 1] + sorted_l[n // 2]) / 2.0
    else:
        median_latency = 0.0

    fastest_latency = 999999.0
    fastest_proxy = "N/A"
    for item in working_list:
        if item.get("total_ms", 999999.0) < fastest_latency:
            fastest_latency = item["total_ms"]
            fastest_proxy = item["host"]

    if fastest_latency == 999999.0:
        fastest_latency = 0.0

    best_health = max([item.get("health_score", 0) for item in working_list]) if working_list else 0

    publish_active = is_publish_mode()

    snapshot = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_checked": checked_count,
        "working_count": working_count,
        "dead_count": dead_count,
        "success_rate": success_rate,
        "average_latency_ms": int(round(avg_latency)),
        "median_latency_ms": int(round(median_latency)),
        "fastest_proxy": fastest_proxy if publish_active else "[REDACTED]",
        "fastest_latency_ms": int(round(fastest_latency)),
        "best_health_score": best_health,
        "top_ranked_proxy": (working_list[0]["host"] if publish_active else "[REDACTED]") if working_list else "N/A"
    }

    # Read history database
    history_data = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history_data = json.load(f)
                if not isinstance(history_data, list):
                    history_data = []
        except Exception:
            history_data = []

    history_data.append(snapshot)

    try:
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history_data, f, indent=2)
    except Exception as e:
        print(f"Error writing to history.json: {e}")


def generate_exports(
    checked_count: int,
    working_proxies: List[Dict[str, Any]],
    dead_proxies: List[Dict[str, Any]]
):
    """
    Saves validation results into various text, JSON, and HTML formats.
    Sorts working proxies by:
      1. Health score (descending)
      2. Latency (ascending)
    """
    os.makedirs("output", exist_ok=True)
    working_sorted = sorted(
        working_proxies,
        key=lambda x: (-x.get("health_score", 0), x.get("total_ms", 999999))
    )

    # Save working.txt
    try:
        with open("output/working.txt", "w", encoding="utf-8") as f:
            for item in working_sorted:
                f.write(f"{item['url']}\n")
    except Exception as e:
        print(f"Error saving working.txt: {e}")

    # Save dead.txt
    try:
        with open("output/dead.txt", "w", encoding="utf-8") as f:
            for item in dead_proxies:
                f.write(f"{item['url']} # Status: {item['status']}\n")
    except Exception as e:
        print(f"Error saving dead.txt: {e}")

    # Save telegram_ready.txt and telegram_import.txt
    for filename in ("telegram_ready.txt", "telegram_import.txt"):
        try:
            with open(f"output/{filename}", "w", encoding="utf-8") as f:
                for item in working_sorted:
                    f.write(f"{item['url']}\n")
        except Exception as e:
            print(f"Error saving {filename}: {e}")

    # Save best_proxy.txt
    try:
        with open("output/best_proxy.txt", "w", encoding="utf-8") as f:
            if working_sorted:
                f.write(f"{working_sorted[0]['url']}\n")
            else:
                f.write("")
    except Exception as e:
        print(f"Error saving best_proxy.txt: {e}")

    # Save top10.txt, top25.txt, top50.txt
    for count in (10, 25, 50):
        try:
            with open(f"output/top{count}.txt", "w", encoding="utf-8") as f:
                for item in working_sorted[:count]:
                    f.write(f"{item['url']}\n")
        except Exception as e:
            print(f"Error saving top{count}.txt: {e}")

    # Save working.json
    working_json_data = []
    for item in working_sorted:
        try:
            parsed = urlparse(item["url"])
            query = parse_qs(parsed.query)
            secret = query["secret"][0].strip()
        except Exception:
            secret = ""

        working_json_data.append({
            "server": item["host"],
            "port": item["port"],
            "secret": secret,
            "latency_ms": round(item.get("total_ms", 0), 1),
            "connect_ms": round(item.get("connect_ms", 0), 1),
            "handshake_ms": round(item.get("handshake_ms", 0), 1),
            "resolve_ms": round(item.get("resolve_ms", 0), 1),
            "type": get_proxy_type(secret),
            "status": "OK",
            "health_score": item.get("health_score", 0)
        })

    try:
        with open("output/working.json", "w", encoding="utf-8") as f:
            json.dump(working_json_data, f, indent=2)
    except Exception as e:
        print(f"Error saving working.json: {e}")

    # Append snapshot to history
    update_history(checked_count, working_sorted, dead_proxies)

    # Save html outputs
    generate_html_dashboard(checked_count, working_sorted, dead_proxies)
    generate_history_html()


def generate_html_dashboard(checked_count: int, working_sorted: List[Dict[str, Any]], dead_proxies: List[Dict[str, Any]]):
    """Generates the static dashboard.html file with beautiful modern dark aesthetics."""
    success_rate = (len(working_sorted) / checked_count * 100) if checked_count > 0 else 0
    
    avg_latency = 0.0
    if working_sorted:
        avg_latency = sum(item.get("total_ms", 0) for item in working_sorted) / len(working_sorted)

    publish_mode_active = is_publish_mode()
    
    if publish_mode_active:
        fastest_proxies = sorted(working_sorted, key=lambda x: x.get("total_ms", 999999))[:5]
        fastest_rows_html = ""
        for idx, item in enumerate(fastest_proxies):
            try:
                parsed = urlparse(item["url"])
                secret = parse_qs(parsed.query)["secret"][0].strip()
            except Exception:
                secret = ""
            ptype = get_proxy_type(secret)
            fastest_rows_html += f"""
            <tr>
                <td class="rank-badge">#{idx+1}</td>
                <td class="font-mono">{item['host']}</td>
                <td>{item['port']}</td>
                <td><span class="badge badge-type">{ptype}</span></td>
                <td class="latency-cell font-mono text-emerald">{item['total_ms']:.1f} ms</td>
                <td class="health-cell font-mono text-cyan">{item.get('health_score', 0)}%</td>
            </tr>
            """

        leaderboard_rows_html = ""
        for idx, item in enumerate(working_sorted[:20]):
            try:
                parsed = urlparse(item["url"])
                secret = parse_qs(parsed.query)["secret"][0].strip()
            except Exception:
                secret = ""
            ptype = get_proxy_type(secret)
            leaderboard_rows_html += f"""
            <tr>
                <td class="rank-badge">#{idx+1}</td>
                <td class="font-mono">{item['host']}:{item['port']}</td>
                <td><span class="badge badge-type">{ptype}</span></td>
                <td class="font-mono text-cyan">{item.get('health_score', 0)}%</td>
                <td class="font-mono text-emerald">{item['total_ms']:.1f} ms</td>
                <td class="font-mono text-slate-400">{item.get('connect_ms', 0):.1f} ms</td>
                <td class="font-mono text-slate-400">{item.get('handshake_ms', 0):.1f} ms</td>
                <td>
                    <button class="btn-copy" onclick="copyToClipboard('{item['url']}')">Copy Link</button>
                </td>
            </tr>
            """
            
        if not working_sorted:
            fastest_rows_html = "<tr><td colspan='6' class='text-center text-slate-500'>No working proxies available</td></tr>"
            leaderboard_rows_html = "<tr><td colspan='8' class='text-center text-slate-500'>No working proxies available</td></tr>"
            
        best_proxy_link = '<a href="best_proxy.txt" class="nav-link" target="_blank">Best Proxy Link</a>'
    else:
        fastest_rows_html = '<tr><td colspan="6" class="text-center text-slate-500" style="text-align: center; padding: 20px; color: #64748b;">Proxy speed champions are hidden in Private Mode (PUBLISH_MODE=false).</td></tr>'
        leaderboard_rows_html = '<tr><td colspan="8" class="text-center text-slate-500" style="text-align: center; padding: 25px; color: #64748b;">Proxy address and secret details are hidden in Private Mode (PUBLISH_MODE=false).</td></tr>'
        best_proxy_link = '<span class="nav-link" style="opacity: 0.5; cursor: not-allowed;" title="Disabled in Private Mode">Best Proxy Link (Private)</span>'

    update_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    trend_summary = get_historical_summary_text()

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MTProto Proxy Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: #121826;
            --border-color: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --emerald: #10b981;
            --emerald-bg: rgba(16, 185, 129, 0.1);
            --rose: #ef4444;
            --rose-bg: rgba(239, 68, 68, 0.1);
            --cyan: #06b6d4;
            --cyan-bg: rgba(6, 182, 212, 0.1);
            --primary: #6366f1;
            --primary-hover: #4f46e5;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: 'Plus Jakarta Sans', sans-serif;
            padding: 2rem 1.5rem;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1280px;
            margin: 0 auto;
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
        }}

        .logo h1 {{
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a5b4fc, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .logo p {{
            color: var(--text-secondary);
            font-size: 0.875rem;
            margin-top: 0.25rem;
        }}

        .last-updated {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            text-align: right;
        }}

        .last-updated span {{
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
        }}

        /* Navigation */
        nav {{
            display: flex;
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}

        .nav-link {{
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 0.9375rem;
            font-weight: 600;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            transition: all 0.2s;
            background-color: #1e293b;
            border: 1px solid var(--border-color);
        }}

        .nav-link:hover {{
            color: var(--text-primary);
            background-color: #334155;
        }}

        .nav-link.active {{
            background-color: var(--primary);
            color: #fff;
            border-color: var(--primary);
        }}

        /* Summary panel */
        .summary-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 2rem;
            font-size: 0.9375rem;
            border-left: 4px solid var(--cyan);
            color: var(--text-primary);
            font-weight: 500;
        }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2.5rem;
        }}

        .stat-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            overflow: hidden;
            transition: transform 0.2s, border-color 0.2s;
        }}

        .stat-card:hover {{
            transform: translateY(-2px);
            border-color: #334155;
        }}

        .stat-label {{
            color: var(--text-secondary);
            font-size: 0.875rem;
            font-weight: 500;
            margin-bottom: 1rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .stat-value {{
            font-size: 2.25rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}

        .stat-card.emerald .stat-value {{ color: var(--emerald); }}
        .stat-card.rose .stat-value {{ color: var(--rose); }}
        .stat-card.cyan .stat-value {{ color: var(--cyan); }}

        .main-layout {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 2rem;
        }}

        @media (min-width: 1024px) {{
            .main-layout {{
                grid-template-columns: 2fr 1fr;
            }}
        }}

        .panel {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.75rem;
            overflow: hidden;
        }}

        .panel-title {{
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .table-container {{
            width: 100%%;
            overflow-x: auto;
        }}

        table {{
            width: 100%%;
            border-collapse: collapse;
            text-align: left;
            font-size: 0.9375rem;
        }}

        th {{
            color: var(--text-secondary);
            font-weight: 500;
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.8125rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        td {{
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }}

        tr:last-child td {{
            border-bottom: none;
        }}

        .rank-badge {{
            font-weight: 600;
            color: var(--text-secondary);
        }}

        .badge {{
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .badge-type {{
            background-color: rgba(99, 102, 241, 0.1);
            color: #a5b4fc;
            border: 1px solid rgba(99, 102, 241, 0.2);
        }}

        .font-mono {{
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
        }}

        .text-emerald {{ color: var(--emerald); }}
        .text-rose {{ color: var(--rose); }}
        .text-cyan {{ color: var(--cyan); }}
        .text-slate-400 {{ color: #94a3b8; }}

        .btn-copy {{
            background-color: #1e293b;
            color: var(--text-primary);
            border: 1px solid var(--border-color);
            padding: 0.375rem 0.75rem;
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.8125rem;
            font-weight: 500;
            transition: all 0.2s;
        }}

        .btn-copy:hover {{
            background-color: var(--primary);
            border-color: var(--primary);
        }}

        #toast {{
            visibility: hidden;
            min-width: 250px;
            background-color: #1e293b;
            color: #fff;
            text-align: center;
            border-radius: 8px;
            padding: 1rem;
            position: fixed;
            z-index: 1000;
            left: 50%%;
            bottom: 30px;
            transform: translateX(-50%%);
            font-size: 0.9375rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
            border: 1px solid var(--primary);
        }}

        #toast.show {{
            visibility: visible;
            -webkit-animation: fadein 0.5s, fadeout 0.5s 2.5s;
            animation: fadein 0.5s, fadeout 0.5s 2.5s;
        }}

        @-webkit-keyframes fadein {{
            from {{bottom: 0; opacity: 0;}} 
            to {{bottom: 30px; opacity: 1;}}
        }}

        @keyframes fadein {{
            from {{bottom: 0; opacity: 0;}}
            to {{bottom: 30px; opacity: 1;}}
        }}

        @-webkit-keyframes fadeout {{
            from {{bottom: 30px; opacity: 1;}} 
            to {{bottom: 0; opacity: 0;}}
        }}

        @keyframes fadeout {{
            from {{bottom: 30px; opacity: 1;}}
            to {{bottom: 0; opacity: 0;}}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <h1>MTProto Proxy Dashboard</h1>
                <p>Self-Updating Verification and Performance Monitoring</p>
            </div>
            <div class="last-updated">
                <p>Last verified: <span id="update-time">{update_time}</span></p>
            </div>
        </header>

        <nav>
            <a href="dashboard.html" class="nav-link active">Dashboard</a>
            <a href="history.html" class="nav-link">Analytics</a>
            {best_proxy_link}
        </nav>

        <div class="summary-card">
            {trend_summary}
        </div>

        <section class="stats-grid">
            <div class="stat-card">
                <span class="stat-label">Total Checked</span>
                <span class="stat-value">{checked_count}</span>
            </div>
            <div class="stat-card emerald">
                <span class="stat-label">Active / Working</span>
                <span class="stat-value">{len(working_sorted)}</span>
            </div>
            <div class="stat-card rose">
                <span class="stat-label">Dead / Inactive</span>
                <span class="stat-value">{len(dead_proxies)}</span>
            </div>
            <div class="stat-card cyan">
                <span class="stat-label">Success Rate</span>
                <span class="stat-value">{success_rate:.1f}%%</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Average Latency</span>
                <span class="stat-value" style="font-size: 1.75rem; color: #cbd5e1;">{avg_latency:.0f} ms</span>
            </div>
        </section>

        <div class="main-layout">
            <div class="panel">
                <div class="panel-title">
                    <span>Quality Leaderboard</span>
                    <span style="font-size: 0.8125rem; font-weight: normal; color: var(--text-secondary);">Sorted by Health Score & Latency</span>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Server Address</th>
                                <th>Type</th>
                                <th>Health</th>
                                <th>Total RTT</th>
                                <th>TCP RTT</th>
                                <th>Handshake</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            {leaderboard_rows_html}
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="panel">
                <div class="panel-title">
                    <span>Top 5 Speed Champions</span>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Host</th>
                                <th>Port</th>
                                <th>Type</th>
                                <th>Latency</th>
                                <th>Health</th>
                            </tr>
                        </thead>
                        <tbody>
                            {fastest_rows_html}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <div id="toast">Proxy Link Copied!</div>

    <script>
        function copyToClipboard(text) {{
            navigator.clipboard.writeText(text).then(function() {{
                var x = document.getElementById("toast");
                x.className = "show";
                setTimeout(function(){{ x.className = x.className.replace("show", ""); }}, 3000);
            }}, function(err) {{
                console.error('Could not copy text: ', err);
            }});
        }}
    </script>
</body>
</html>
"""

    try:
        with open("output/dashboard.html", "w", encoding="utf-8") as f:
            f.write(html_content)
    except Exception as e:
        print(f"Error saving dashboard.html: {e}")


def generate_history_html():
    """Generates a dark-themed history.html analytics page displaying 5 interactive Chart.js line charts."""
    history_file = "output/history.json"
    if not os.path.exists(history_file):
        return

    try:
        with open(history_file, "r", encoding="utf-8") as f:
            history_data = json.load(f)
            if not isinstance(history_data, list):
                return
    except Exception as e:
        print(f"Error reading history.json for HTML generation: {e}")
        return

    if not history_data:
        return

    if is_publish_mode():
        best_proxy_link = '<a href="best_proxy.txt" class="nav-link" target="_blank">Best Proxy Link</a>'
    else:
        best_proxy_link = '<span class="nav-link" style="opacity: 0.5; cursor: not-allowed;" title="Disabled in Private Mode">Best Proxy Link (Private)</span>'

    # Extract historical parameters
    timestamps = [e.get("timestamp", "") for e in history_data]
    working_counts = [e.get("working_count", 0) for e in history_data]
    success_rates = [e.get("success_rate", 0.0) for e in history_data]
    avg_latencies = [e.get("average_latency_ms", 0) for e in history_data]
    fastest_latencies = [e.get("fastest_latency_ms", 0) for e in history_data]
    best_healths = [e.get("best_health_score", 0) for e in history_data]

    # Clean timestamps for labels
    labels = []
    for t in timestamps:
        try:
            # Reformat e.g., 2026-06-18T18:00:00Z -> 06-18 18:00
            labels.append(f"{t[5:10]} {t[11:16]}")
        except Exception:
            labels.append(t)

    # Group by calendar date for daily snapshots
    daily_snapshots = {}
    for entry in history_data:
        date_str = entry.get("timestamp", "2026-06-18")[:10]
        daily_snapshots[date_str] = entry

    sorted_dates = sorted(daily_snapshots.keys())
    daily_entries = [daily_snapshots[d] for d in sorted_dates]

    latest = daily_entries[-1]
    prev_entries = daily_entries[:-1]
    recent_7 = prev_entries[-7:] if len(prev_entries) >= 7 else prev_entries
    recent_30 = prev_entries[-30:] if len(prev_entries) >= 30 else prev_entries

    # Calculate 7-day Averages
    avg_success_7 = sum(e["success_rate"] for e in recent_7) / len(recent_7) if recent_7 else latest["success_rate"]
    avg_latency_7 = sum(e["average_latency_ms"] for e in recent_7) / len(recent_7) if recent_7 else latest["average_latency_ms"]
    avg_working_7 = sum(e["working_count"] for e in recent_7) / len(recent_7) if recent_7 else latest["working_count"]

    # Calculate 30-day Averages
    avg_success_30 = sum(e["success_rate"] for e in recent_30) / len(recent_30) if recent_30 else latest["success_rate"]
    avg_latency_30 = sum(e["average_latency_ms"] for e in recent_30) / len(recent_30) if recent_30 else latest["average_latency_ms"]
    avg_working_30 = sum(e["working_count"] for e in recent_30) / len(recent_30) if recent_30 else latest["working_count"]

    # Determine trend indicators
    success_diff = latest["success_rate"] - avg_success_7
    latency_diff = latest["average_latency_ms"] - avg_latency_7
    working_diff = latest["working_count"] - avg_working_7

    def get_trend_badge(diff: float, invert: bool = False) -> Tuple[str, str]:
        # returns (label, css_class)
        # invert=True is for latency where lower is better
        threshold = 15.0 if "latency" in str(diff) else 2.0
        if invert:
            if diff < -threshold:
                return "Improving", "trend-improving"
            elif diff > threshold:
                return "Declining", "trend-declining"
            else:
                return "Stable", "trend-stable"
        else:
            if diff > threshold:
                return "Improving", "trend-improving"
            elif diff < -threshold:
                return "Declining", "trend-declining"
            else:
                return "Stable", "trend-stable"

    trend_success_label, trend_success_class = get_trend_badge(success_diff)
    trend_latency_label, trend_latency_class = get_trend_badge(latency_diff, invert=True)
    trend_working_label, trend_working_class = get_trend_badge(working_diff)

    trend_summary = get_historical_summary_text()
    update_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    # Format JSON strings for insertion directly in JS
    js_labels = json.dumps(labels)
    js_working = json.dumps(working_counts)
    js_success = json.dumps(success_rates)
    js_avg_latency = json.dumps(avg_latencies)
    js_fastest_latency = json.dumps(fastest_latencies)
    js_best_health = json.dumps(best_healths)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Historical Analytics - MTProto Manager</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: #121826;
            --border-color: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --emerald: #10b981;
            --emerald-bg: rgba(16, 185, 129, 0.1);
            --rose: #ef4444;
            --rose-bg: rgba(239, 68, 68, 0.1);
            --cyan: #06b6d4;
            --cyan-bg: rgba(6, 182, 212, 0.1);
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --yellow: #f59e0b;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: 'Plus Jakarta Sans', sans-serif;
            padding: 2rem 1.5rem;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1280px;
            margin: 0 auto;
        }}

        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1.5rem;
        }}

        .logo h1 {{
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a5b4fc, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .logo p {{
            color: var(--text-secondary);
            font-size: 0.875rem;
            margin-top: 0.25rem;
        }}

        .last-updated {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            text-align: right;
        }}

        .last-updated span {{
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
        }}

        /* Navigation */
        nav {{
            display: flex;
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}

        .nav-link {{
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 0.9375rem;
            font-weight: 600;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            transition: all 0.2s;
            background-color: #1e293b;
            border: 1px solid var(--border-color);
        }}

        .nav-link:hover {{
            color: var(--text-primary);
            background-color: #334155;
        }}

        .nav-link.active {{
            background-color: var(--primary);
            color: #fff;
            border-color: var(--primary);
        }}

        /* Trend Summary Card */
        .summary-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 2rem;
            font-size: 0.9375rem;
            border-left: 4px solid var(--primary);
            color: var(--text-primary);
            font-weight: 500;
        }}

        /* Stats Cards */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.25rem;
            margin-bottom: 2.5rem;
        }}

        .stat-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }}

        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }}

        .stat-label {{
            color: var(--text-secondary);
            font-size: 0.8125rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        .trend-badge {{
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.25rem 0.5rem;
            border-radius: 6px;
            text-transform: uppercase;
        }}

        .trend-improving {{
            background-color: var(--emerald-bg);
            color: var(--emerald);
            border: 1px solid rgba(16, 185, 129, 0.2);
        }}

        .trend-stable {{
            background-color: rgba(148, 163, 184, 0.1);
            color: var(--text-secondary);
            border: 1px solid rgba(148, 163, 184, 0.2);
        }}

        .trend-declining {{
            background-color: var(--rose-bg);
            color: var(--rose);
            border: 1px solid rgba(239, 68, 68, 0.2);
        }}

        .stat-main {{
            display: flex;
            align-items: baseline;
            gap: 0.75rem;
            margin-bottom: 0.75rem;
        }}

        .stat-value {{
            font-size: 2.25rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}

        .stat-card.success-card .stat-value {{ color: var(--cyan); }}
        .stat-card.latency-card .stat-value {{ color: var(--yellow); }}

        .averages-sub {{
            font-size: 0.8125rem;
            color: var(--text-secondary);
            line-height: 1.5;
        }}

        .averages-sub span {{
            color: var(--text-primary);
            font-family: 'JetBrains Mono', monospace;
        }}

        /* Chart Layout */
        .charts-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 2rem;
            margin-bottom: 2rem;
        }}

        @media (min-width: 1024px) {{
            .charts-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}

        .chart-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
        }}

        .chart-card h3 {{
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 1.25rem;
            color: var(--text-primary);
        }}

        .chart-wrapper {{
            position: relative;
            height: 320px;
            width: 100%%;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <h1>Historical Analytics</h1>
                <p>MTProto Proxy Quality and Performance Over Time</p>
            </div>
            <div class="last-updated">
                <p>Last verified: <span id="update-time">{update_time}</span></p>
            </div>
        </header>

        <nav>
            <a href="dashboard.html" class="nav-link">Dashboard</a>
            <a href="history.html" class="nav-link active">Analytics</a>
            {best_proxy_link}
        </nav>

        <div class="summary-card">
            {trend_summary}
        </div>

        <!-- Trend metrics row -->
        <section class="stats-grid">
            <!-- Working proxies trend -->
            <div class="stat-card">
                <div class="card-header">
                    <span class="stat-label">Active Proxies</span>
                    <span class="trend-badge {trend_working_class}">{trend_working_label}</span>
                </div>
                <div class="stat-main">
                    <span class="stat-value">{latest['working_count']}</span>
                </div>
                <div class="averages-sub">
                    <p>7-Day Avg: <span>{avg_working_7:.1f}</span></p>
                    <p>30-Day Avg: <span>{avg_working_30:.1f}</span></p>
                </div>
            </div>

            <!-- Success rate trend -->
            <div class="stat-card success-card">
                <div class="card-header">
                    <span class="stat-label">Success Rate</span>
                    <span class="trend-badge {trend_success_class}">{trend_success_label}</span>
                </div>
                <div class="stat-main">
                    <span class="stat-value">{latest['success_rate']:.1f}%%</span>
                </div>
                <div class="averages-sub">
                    <p>7-Day Avg: <span>{avg_success_7:.1f}%%</span></p>
                    <p>30-Day Avg: <span>{avg_success_30:.1f}%%</span></p>
                </div>
            </div>

            <!-- Average latency trend -->
            <div class="stat-card latency-card">
                <div class="card-header">
                    <span class="stat-label">Average RTT</span>
                    <span class="trend-badge {trend_latency_class}">{trend_latency_label}</span>
                </div>
                <div class="stat-main">
                    <span class="stat-value">{latest['average_latency_ms']} ms</span>
                </div>
                <div class="averages-sub">
                    <p>7-Day Avg: <span>{avg_latency_7:.0f} ms</span></p>
                    <p>30-Day Avg: <span>{avg_latency_30:.0f} ms</span></p>
                </div>
            </div>
        </section>

        <!-- Charts grid -->
        <div class="charts-grid">
            <div class="chart-card">
                <h3>Active Working Proxies Over Time</h3>
                <div class="chart-wrapper">
                    <canvas id="chartWorking"></canvas>
                </div>
            </div>

            <div class="chart-card">
                <h3>Success Rate Over Time (%%)</h3>
                <div class="chart-wrapper">
                    <canvas id="chartSuccess"></canvas>
                </div>
            </div>

            <div class="chart-card">
                <h3>Average Connection Latency Over Time (ms)</h3>
                <div class="chart-wrapper">
                    <canvas id="chartAverageLatency"></canvas>
                </div>
            </div>

            <div class="chart-card">
                <h3>Fastest Proxy Latency Over Time (ms)</h3>
                <div class="chart-wrapper">
                    <canvas id="chartFastestLatency"></canvas>
                </div>
            </div>

            <div class="chart-card" style="grid-column: 1 / -1;">
                <h3>Best Health Score Over Time (%%)</h3>
                <div class="chart-wrapper">
                    <canvas id="chartBestHealth"></canvas>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Chart configuration options
        const chartOptions = {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                legend: {{
                    display: false
                }},
                tooltip: {{
                    backgroundColor: '#1e293b',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: '#334155',
                    borderWidth: 1,
                    padding: 10,
                    bodyFont: {{
                        family: 'Plus Jakarta Sans'
                    }}
                }}
            }},
            scales: {{
                x: {{
                    grid: {{
                        color: 'rgba(255, 255, 255, 0.05)',
                        borderColor: '#1e293b'
                    }},
                    ticks: {{
                        color: '#94a3b8',
                        font: {{
                            family: 'Plus Jakarta Sans',
                            size: 10
                        }},
                        maxRotation: 45,
                        minRotation: 45
                    }}
                }},
                y: {{
                    grid: {{
                        color: 'rgba(255, 255, 255, 0.05)',
                        borderColor: '#1e293b'
                    }},
                    ticks: {{
                        color: '#94a3b8',
                        font: {{
                            family: 'Plus Jakarta Sans',
                            size: 10
                        }}
                    }}
                }}
            }}
        }};

        // Data arrays injected from Python backend
        const labels = {js_labels};
        const dataWorking = {js_working};
        const dataSuccess = {js_success};
        const dataAverageLatency = {js_avg_latency};
        const dataFastestLatency = {js_fastest_latency};
        const dataBestHealth = {js_best_health};

        // Render Working Proxies
        new Chart(document.getElementById('chartWorking').getContext('2d'), {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    data: dataWorking,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.05)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }}]
            }},
            options: chartOptions
        }});

        // Render Success Rate
        new Chart(document.getElementById('chartSuccess').getContext('2d'), {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    data: dataSuccess,
                    borderColor: '#06b6d4',
                    backgroundColor: 'rgba(6, 182, 212, 0.05)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }}]
            }},
            options: chartOptions
        }});

        // Render Average Latency
        new Chart(document.getElementById('chartAverageLatency').getContext('2d'), {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    data: dataAverageLatency,
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.05)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }}]
            }},
            options: chartOptions
        }});

        // Render Fastest Latency
        new Chart(document.getElementById('chartFastestLatency').getContext('2d'), {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    data: dataFastestLatency,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.05)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }}]
            }},
            options: chartOptions
        }});

        // Render Best Health Score
        new Chart(document.getElementById('chartBestHealth').getContext('2d'), {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    data: dataBestHealth,
                    borderColor: '#8b5cf6',
                    backgroundColor: 'rgba(139, 92, 246, 0.05)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointHoverRadius: 5
                }}]
            }},
            options: chartOptions
        }});
    </script>
</body>
</html>
"""

    try:
        with open("output/history.html", "w", encoding="utf-8") as f:
            f.write(html_content)
    except Exception as e:
        print(f"Error saving history.html: {e}")
