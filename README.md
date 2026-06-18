# MTProto Proxy Finder & Manager

[![Auto-update MTProto Proxies](https://github.com/[USERNAME]/[REPOSITORY]/actions/workflows/update.yml/badge.svg)](https://github.com/[USERNAME]/[REPOSITORY]/actions/workflows/update.yml)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Active-emerald?style=flat&logo=github)](https://[USERNAME].github.io/[REPOSITORY]/)

A production-quality, self-updating MTProto proxy discovery, verification, ranking, and management platform written in Python 3.13. 

It performs a **real cryptographic MTProto handshake** (generating `req_pq_multi` and validating the returned `resPQ` constructor and cryptographic nonce) to prove that Telegram traffic can traverse each proxy, rather than simply checking if a TCP port is open.

---

## 🚀 Quick Start

### 1. Installation
The project requires Python 3.13 and has only a single dependency (`cryptography`):
```bash
pip install -r requirements.txt
```

### 2. Run the Desktop GUI
Launch the responsive dark-themed desktop app to scan, update, export, and copy links interactively:
```bash
python gui.py
```

### 3. Run the CLI Scraper & Verification
Scrape candidate sources, run checks, and generate reports from the command line:
```bash
python checker.py --update
```

### 4. Run Unit Tests
Verify cryptographic codecs and URL normalizers:
```bash
python -m unittest discover -s tests
```

---

## 📂 Repository Structure & Generated Outputs

All real scan results are generated in the `output/` directory, and archived failure records are stored in `archive/`. Both of these directories are strictly ignored by git to protect your privacy and prevent accidental leaks of active proxy servers. 

For new users or documentation references, static sample output templates are provided in the `examples/` directory and are tracked by git.

```
.
├── checker.py              # Unified CLI controller & launcher
├── gui.py                  # Desktop GUI launcher
├── requirements.txt        # Project dependencies
├── index.html              # Redirect page for GitHub Pages
├── core/                   # Handshake logic, health scores, and state
├── scrapers/               # Proxy collectors and scraper engines
├── exports/                # File export managers and HTML dashboard builders
├── gui/                    # Tkinter desktop app framework
├── tests/                  # Test suites
│
├── examples/               # Tracked template examples for beginners
│   ├── sample_working.txt  # Sample verified proxy URLs list
│   ├── sample_working.json # Sample benchmarking database
│   └── sample_best_proxy.txt # Sample best proxy URL
│
├── output/                 # GENERATED FILES DIRECTORY (git-ignored)
│   ├── dashboard.html      # Visual monitoring dashboard (updates every check)
│   ├── history.html        # Chart.js analytics page showing historical trends
│   ├── working.txt         # List of active verified proxy URLs
│   ├── working.json        # Detailed benchmarking metrics database
│   ├── best_proxy.txt      # The single fastest, highest-quality proxy URL
│   ├── top10/top25/top50.txt # Curated subsets of top performing proxies
│   ├── telegram_ready.txt  # Ready-to-import lists for Telegram Clients
│   ├── proxy_state.json    # Historical health score tracking database
│   └── history.json        # Snapshot metrics for trends & Chart.js views
│
└── archive/                # ARCHIVED DATA DIRECTORY (git-ignored)
    └── archive_dead.txt    # Saved list of persistent dead proxies (3+ failures)
```

---

## 🔒 Privacy, Security & Publish Modes

To prevent accidental public leaks of verified proxy inventories or private details, the project implements a strict safety mechanism controlled by `PUBLISH_MODE`.

Copy `.env.example` to `.env` to configure your preference locally:
```bash
cp .env.example .env
```

### 1. Private Mode (`PUBLISH_MODE=false`) - **Default**
* **Local Operation**: Scanning locally generates real, live proxy lists in `output/` for your own personal use.
* **Git Exclusions**: `.gitignore` automatically prevents active proxy lists, state files, and secrets from being committed.
* **Aggregated Dashboards**: The generated `dashboard.html` and `history.html` hide all server IPs, ports, and secrets, displaying only aggregate stats (e.g. success rate, latencies, total count, history charts).
* **GitHub Actions**: Automated runs on GitHub will only commit the public aggregated dashboards and run tests; no active lists are published.

### 2. Publish Mode (`PUBLISH_MODE=true`)
* **Open Dashboard**: Dashboards are generated with full tables, quality leaderboards, speed champions, and one-click import links.
* **Exports Published**: Verified lists and JSON databases are committed back to the repository.
* **Safety Gates**:
  1. **Manual Setup**: You must explicitly define `PUBLISH_MODE` as `true` in your **GitHub Repository Variables** or **Secrets** to enable Publish Mode on GitHub.
  2. **Branch Protection**: Publish Mode actions are strictly restricted to runs on the `main` branch or manual `workflow_dispatch` triggers. Test branches always fall back to Private Mode.

---

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
