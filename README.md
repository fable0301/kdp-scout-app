# 📚 KDP Scout App

**A free, open-source keyword research & niche analysis tool for Amazon KDP publishers.**

KDP Scout App helps self-publishers find profitable niches, trending keywords, and market opportunities across **5 data sources** — all from a single desktop application.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 🚀 Installation — One Click, That's It

**No prerequisites. No terminal. No configuration.**

1. **Download** or clone this repository
2. **Double-click `CLICK ME.bat`**
3. ☕ Wait 2-5 minutes — everything is automatic

The batch script handles **everything** for you:
- ✅ Detects if Python is installed — downloads & installs it if not
- ✅ Installs all dependencies (PyQt6, matplotlib, etc.)
- ✅ Compiles the app into a standalone `.exe`
- ✅ Creates a shortcut on your Desktop
- ✅ Launches the app automatically

**One click = one install = ready to use.** 🎯

---

## 🎯 Features

### 5 Data Sources

| Source | Tools | Description |
|--------|-------|-------------|
| 🛒 **Amazon** | 8 tools | Keywords, Trending, Niche Analyzer, BSR Tracker, Category Explorer, Competitor Analysis, ASIN Lookup, Review Analyzer |
| 🔍 **Google** | 3 tools | G-Keywords, G-Trending, G-Books |
| 🎵 **TikTok** | 1 tool | BookTok Trends — discover trending book topics on TikTok |
| 🤖 **Reddit** | 1 tool | Reddit Demand — analyze book demand signals from subreddits |
| 📚 **Goodreads** | 1 tool | GR-Explorer — search Goodreads shelves, lists & Open Library metadata |

### Key Capabilities

- **Keyword Research** — Find high-demand, low-competition keywords on Amazon & Google
- **Niche Analysis** — Evaluate niche profitability with BSR data, reviews, and competition metrics
- **Trend Detection** — Spot emerging trends from TikTok BookTok and Reddit communities
- **Goodreads Intelligence** — Explore popular shelves, reading lists, and book metadata
- **Competitor Analysis** — Track competitors' strategies with ASIN lookup and review analysis
- **Export** — Export all results to CSV for further analysis

---

## 📁 Project Structure

```
kdp-scout-app/
├── CLICK ME.bat                 ← Double-click to install & run
├── requirements.txt
├── kdp_scout_gui.py
├── kdp_scout_gui.spec           # PyInstaller spec
├── kdp_scout/
│   ├── __init__.py              # Version 0.4.0
│   ├── __main__.py              # Entry point
│   ├── config.py                # Configuration & rate limits
│   ├── collectors/              # Data collection modules
│   │   ├── amazon_*.py          # Amazon scrapers & API
│   │   ├── google_*.py          # Google trends & books
│   │   ├── reddit_demand.py     # Reddit subreddit analysis
│   │   ├── tiktok_booktok.py    # TikTok BookTok scraper
│   │   └── goodreads.py         # Goodreads + Open Library
│   └── gui/
│       ├── app.py               # Application entry
│       ├── main_window.py       # Main window with 5-source sidebar
│       ├── pages/               # UI pages for each tool
│       └── workers/             # Background workers (threading)
```

---

## ⚡ Performance

All collectors use **`ThreadPoolExecutor`** for parallel fetching:
- Amazon: concurrent keyword & BSR lookups
- Google: parallel trend queries
- Goodreads: 4 workers for scraping, 6 workers for Open Library API
- Session reuse & smart rate limiting to avoid bans

---

## 🙏 Credits & Origin

This project is a fork/enhancement of the original **KDP Scout** by [rxpelle](https://github.com/rxpelle):

- **Original repo**: [github.com/rxpelle/kdp-scout](https://github.com/rxpelle/kdp-scout)
- **Original announcement**: [r/KDP — Free open-source KDP keyword research tool](https://www.reddit.com/r/KDP/comments/1rn0q0u/free_opensource_kdp_keyword_research_tool_no/)

### What's new in this fork (v0.4.0)

- ✅ **Goodreads Explorer** — New data source with Goodreads scraping + Open Library API
- ✅ **Reddit Demand** — Now wired into the sidebar (existed but wasn't accessible)
- ✅ **TikTok BookTok** — Now wired into the sidebar (existed but wasn't accessible)
- ✅ **5 data sources** in the sidebar instead of 2
- ✅ **Speed optimizations** — ThreadPoolExecutor on all collectors
- ✅ Renamed to **KDP Scout App**

---

## 📄 License

MIT — Free to use, modify, and distribute.
