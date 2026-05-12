# 📚 Scout

**A free, open-source keyword research & niche analysis tool for Amazon KDP publishers — now with POD (Print on Demand) support.**

Scout helps self-publishers find profitable niches, trending keywords, and market opportunities across **5 data sources for KDP** and **4 data sources for POD** — all from a single desktop application with seamless mode switching.

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

### KDP Mode — 5 Data Sources

| Source | Tools | Description |
|--------|-------|-------------|
| 🛒 **Amazon** | 8 tools | Keywords, Trending, Niche Analyzer, BSR Tracker, Category Explorer, Competitor Analysis, ASIN Lookup, Review Analyzer |
| 🔍 **Google** | 3 tools | G-Keywords, G-Trending, G-Books |
| 🎵 **TikTok** | 1 tool | BookTok Trends — discover trending book topics on TikTok |
| 🤖 **Reddit** | 1 tool | Reddit Demand — analyze book demand signals from subreddits |
| 📚 **Goodreads** | 1 tool | GR-Explorer — search Goodreads shelves, lists & Open Library metadata |

### POD Mode — 4 Data Sources (New in v0.4.0+)

**Objective**: Help POD sellers find profitable niches, analyze competition, and discover trending designs across Amazon Merch, Etsy, Redbubble, and Pinterest.

| Source | Tools | Description |
|--------|-------|-------------|
| 🛒 **Amazon Merch** | 2 tools | Keywords (mine & score), Product Lookup |
| 🔍 **Google** | 2 tools | Trending, Market Overview |
| 📌 **Pinterest** | 1 tool | Pinterest Explorer — trends & board analysis |
| 🎨 **Etsy** | 2 tools | Competitors, Product Lookup |

### Key Capabilities

**KDP Publishers:**
- **Keyword Research** — Find high-demand, low-competition keywords on Amazon & Google
- **Niche Analysis** — Evaluate niche profitability with BSR data, reviews, and competition metrics
- **Trend Detection** — Spot emerging trends from TikTok BookTok and Reddit communities
- **Goodreads Intelligence** — Explore popular shelves, reading lists, and book metadata
- **Competitor Analysis** — Track competitors' strategies with ASIN lookup and review analysis

**POD Sellers (New):**
- **POD Keyword Mining** — Extract keywords from Amazon Merch autocomplete with scoring
- **Trending Analysis** — Discover hot niches from Reddit, Google Trends & Pinterest
- **Niche Analyzer** — Evaluate POD niche profitability (demand, competition, trends)
- **Competitor Research** — Analyze top Etsy/Redbubble listings for any niche
- **Market Overview** — Get hot niches, rising trends & opportunities in one dashboard
- **Product Lookup** — Lookup any Amazon Merch product by ASIN/URL to extract keywords
- **Seeds Generator** — Auto-generate keyword seeds by category (professions, animals, hobbies, etc.)

**Shared:**
- **Export** — Export all results to CSV for further analysis
- **Mode Switching** — Click the logo to toggle between KDP (blue) and POD (purple) modes

---

## 📁 Project Structure

```
kdp-scout-app/
├── CLICK ME.bat                 ← Double-click to install & run
├── requirements.txt
├── scout_gui.py
├── scout_gui.spec           # PyInstaller spec
├── scout/
│   ├── __init__.py              # Version 1.0
│   ├── __main__.py              # Entry point
│   ├── config.py                # Configuration & rate limits
│   ├── collectors/              # Data collection modules
│   │   ├── amazon_*.py          # Amazon scrapers & API
│   │   ├── google_*.py          # Google trends & books
│   │   ├── reddit_demand.py     # Reddit subreddit analysis
│   │   ├── tiktok_booktok.py    # TikTok BookTok scraper
│   │   ├── goodreads.py         # Goodreads + Open Library
│   │   └── pod_*.py             # POD scrapers (Merch, Etsy, Redbubble, Pinterest)
│   └── gui/
│       ├── app.py               # Application entry
│       ├── main_window.py       # Main window with KDP/POD dual mode
│       ├── pages/               # UI pages for each tool (KDP + POD)
│       ├── widgets/             # Reusable widgets (DataTable, ScoreGauge, etc.)
│       └── workers/             # Background workers (threading)
```

---

## ⚡ Performance

All collectors use **`ThreadPoolExecutor`** for parallel fetching:
- Amazon: concurrent keyword & BSR lookups
- Google: parallel trend queries
- Goodreads: 4 workers for scraping, 6 workers for Open Library API
- POD: Concurrent mining across multiple platforms

---

## 🙏 Credits & Origin

This project is a fork/enhancement of the original **KDP Scout** by [rxpelle](https://github.com/rxpelle):

- **Original repo**: [github.com/rxpelle/kdp-scout](https://github.com/rxpelle/kdp-scout)
- **Original announcement**: [r/KDP — Free open-source KDP keyword research tool](https://www.reddit.com/r/KDP/comments/1rn0q0u/free_opensource_kdp_keyword_research_tool_no/)

### What's new in this fork:

**v1.0 (Current):**
- ✅ **POD Mode Complete** — Full Print-on-Demand interface with 9 tools
- ✅ **Dual Logos** — Blue KDP logo / Purple POD logo (click to switch modes)
- ✅ **Version Link** — Click version number (v1.0) to open GitHub repo
- ✅ **Larger Logos** — Now 68×68px for better visibility
- ✅ **POD Workers** — Specialized PodMineAmazonWorker, PodProductLookupAmazonWorker
- ✅ **Find For Me v2.0** — Complete rewrite with velocity-based trend detection, parallel pipeline, and dynamic seed generation from TikTok & Reddit

**v0.4.0-v0.4.8:**
- ✅ **POD Support Added** — Amazon Merch, Etsy, Redbubble, Pinterest integration
- ✅ **9 POD Pages** — Keywords, Trending, Niche Analyzer, Find For Me, Competitors, Seeds, Pinterest, Product Lookup, Market Overview
- ✅ **Goodreads Explorer** — New KDP data source with Goodreads scraping + Open Library API
- ✅ **Reddit Demand** — Now wired into the sidebar (existed but wasn't accessible)
- ✅ **TikTok BookTok** — Now wired into the sidebar (existed but wasn't accessible)
- ✅ **5 KDP data sources** + **4 POD data sources** in the sidebar
- ✅ **Speed optimizations** — ThreadPoolExecutor on all collectors
- ✅ **Mode Switching** — Click logo to toggle between KDP (blue) and POD (purple) modes
- ✅ **Renamed to Scout**

---

## 📄 License

Free to use for any purpose. You may not modify, sublicense, or redistribute this software without my prior consent.
