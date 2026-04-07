from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QMessageBox, QLineEdit, QSpinBox, QToolButton, QMenu,
    QWidgetAction,
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.base_worker import BaseWorker
from kdp_scout.gui.search_history import SearchHistory




TRENDING_COLUMNS = ["keyword", "source", "position"]

TRENDING_DISPLAY_NAMES = {
    "keyword": "Keyword / Title",
    "source": "Source",
    "position": "Rank / Info",
}

AMAZON_CATEGORIES = [
    ("All Categories",    None),
    ("Romance",           "romance"),
    ("Mystery & Thriller","mystery_thriller"),
    ("Sci-Fi",            "sci_fi"),
    ("Fantasy",           "fantasy"),
    ("Self-Help",         "self_help"),
    ("Business",          "business"),
    ("Young Adult",       "young_adult"),
    ("Children",          "children"),
    ("Horror",            "horror"),
    ("Literary Fiction",  "literary_fiction"),
    ("Biographies",       "biographies"),
    ("True Crime",        "true_crime"),
    ("Cookbooks",         "cookbooks"),
    ("Health & Fitness",  "health_fitness"),
]

# Extended columns for Movers & Shakers (richer data)
MOVERS_COLUMNS = ["title", "author", "asin", "bsr_rank", "change_pct", "source"]
MOVERS_DISPLAY_NAMES = {
    "title": "Title",
    "author": "Author",
    "asin": "ASIN",
    "bsr_rank": "Rank",
    "change_pct": "BSR Change",
    "source": "Category",
}

# Extended columns for Most Wished For / Hot New Releases
WISHLIST_COLUMNS = ["title", "author", "asin", "position"]
WISHLIST_DISPLAY_NAMES = {
    "title": "Book Title",
    "author": "Author",
    "asin": "ASIN",
    "position": "Rank",
}

# Columns for Keyword Search mode (richest data from amazon_search)
KEYWORD_SEARCH_COLUMNS = [
    "position", "asin", "title", "author", "bsr",
    "review_count", "avg_rating", "price_kindle", "ku_eligible", "series", "marketplace",
]
KEYWORD_SEARCH_DISPLAY_NAMES = {
    "position": "#",
    "asin": "ASIN",
    "title": "Title",
    "author": "Author",
    "bsr": "BSR",
    "review_count": "Reviews",
    "avg_rating": "Rating",
    "price_kindle": "Price (K)",
    "ku_eligible": "KU",
    "series": "Series",
    "marketplace": "MP",
}

MARKETPLACES = ["us", "uk", "de", "fr", "ca", "au", "jp", "es", "it"]

SORT_OPTIONS = [
    ("Bestsellers", "salesrank"),
    ("New Releases", "date-rank"),
    ("Relevance", "relevancerank"),
]


class TrendingWorker(BaseWorker):
    """Worker for discovering trending keywords and books."""

    MODES = {
        "kindle":            "Bestsellers - Kindle",
        "kindle_free":       "Bestsellers - Free Kindle",
        "kindle_new":        "Hot New Releases",
        "kindle_movers":     "Movers & Shakers",
        "most_wished":       "Most Wished For",
        "also_bought":       "Also Bought clusters",
        "keyword_search":    "Keyword Search",
    }

    def __init__(self, mode: str = "trending", list_type: str = "kindle",
                 asin: str = None, category: str = None,
                 seed: str = None, sort_by: str = None,
                 marketplaces: list = None, max_results: int = 50,
                 parent=None):
        super().__init__(parent)
        self.mode = mode
        self.list_type = list_type
        self.asin = asin
        self.category = category or None
        self.seed = seed
        self.sort_by = sort_by
        self.marketplaces = marketplaces or ["us"]
        self.max_results = max_results

    def run_task(self):
        results = []

        def progress_cb(completed, total):
            self.progress.emit(completed, total)

        if self.mode == "bestseller":
            from kdp_scout.collectors.trending import scrape_bestseller_keywords

            self.status.emit(f"Scraping Amazon bestseller list: {self.list_type}...")
            self.log.emit(f"Scraping bestseller page: {self.list_type}")

            raw = scrape_bestseller_keywords(
                list_type=self.list_type, category=self.category,
                progress_callback=progress_cb,
            )
            for i, (kw, info) in enumerate(raw):
                results.append({
                    "keyword": kw,
                    "source": self.list_type.replace("_", " ").title(),
                    "position": info,
                })

        elif self.mode == "kindle_movers":
            from kdp_scout.collectors.trending import scrape_movers_shakers

            self.status.emit("Scraping Movers & Shakers...")
            self.log.emit("Fetching Kindle Movers & Shakers (hourly refresh)")

            raw = scrape_movers_shakers(category=self.category, progress_callback=progress_cb, cancel_check=lambda: self.is_cancelled)
            if self.is_cancelled: return
            for item in raw:
                title = item.get("title", "") or item.get("keyword", "")
                source_val = item.get("source", "Movers & Shakers")
                change = item.get("bsr_change", "")
                change_str = f"+{change}%" if change else ""
                results.append({
                    "title": title,
                    "author": item.get("author", ""),
                    "asin": item.get("asin", ""),
                    "bsr_rank": str(item.get("rank", "")),
                    "change_pct": change_str,
                    "source": source_val.replace("Movers & Shakers: ", "").strip(),
                })

        elif self.mode == "most_wished":
            from kdp_scout.collectors.trending import scrape_most_wished_for

            self.status.emit("Scraping Most Wished For...")
            self.log.emit("Fetching Amazon Most Wished For — Kindle books")

            raw = scrape_most_wished_for(category=self.category, progress_callback=progress_cb, cancel_check=lambda: self.is_cancelled)
            if self.is_cancelled: return
            for item in raw:
                results.append({
                    "title": item.get("title", ""),
                    "asin": item.get("asin", ""),
                    "author": item.get("author", ""),
                    "source": "Most Wished For",
                    "position": str(item.get("rank", "")),
                })

        elif self.mode == "hot_new":
            from kdp_scout.collectors.trending import scrape_hot_new_releases

            self.status.emit("Scraping Hot New Releases...")
            self.log.emit("Fetching Amazon Hot New Releases — Kindle")

            raw = scrape_hot_new_releases(category=self.category, progress_callback=progress_cb, cancel_check=lambda: self.is_cancelled)
            if self.is_cancelled: return
            for item in raw:
                results.append({
                    "title": item.get("title", ""),
                    "asin": item.get("asin", ""),
                    "author": item.get("author", ""),
                    "source": "Hot New Releases",
                    "position": str(item.get("rank", "")),
                })

        elif self.mode == "also_bought":
            from kdp_scout.collectors.trending import scrape_also_bought

            if not self.asin:
                raise ValueError("ASIN is required for Also Bought scraping")

            self.status.emit(f"Fetching Also Bought for {self.asin}...")
            self.log.emit(f"Scraping 'Customers also bought' for ASIN: {self.asin}")

            raw = scrape_also_bought(self.asin, progress_callback=progress_cb, cancel_check=lambda: self.is_cancelled)
            if self.is_cancelled: return
            for i, item in enumerate(raw):
                results.append({
                    "title": item.get("title", ""),
                    "asin": item.get("asin", ""),
                    "author": item.get("author", ""),
                    "source": f"Also Bought ({self.asin})",
                    "position": str(i + 1),
                })

        elif self.mode == "keyword_search":
            from kdp_scout.collectors.amazon_search import search_kindle

            if not self.seed:
                raise ValueError("Seed keyword is required for Keyword Search")

            sort_label = dict(SORT_OPTIONS).get(self.sort_by, self.sort_by) if self.sort_by else "Relevance"
            # Reverse lookup: value → label
            for lbl, val in SORT_OPTIONS:
                if val == self.sort_by:
                    sort_label = lbl
                    break

            mps_label = ", ".join(mp.upper() for mp in self.marketplaces)
            self.status.emit(
                f"Searching Amazon [{mps_label}] — {sort_label} for '{self.seed}'..."
            )
            self.log.emit(
                f"Keyword Search | seed='{self.seed}' | sort={sort_label} | "
                f"marketplaces={mps_label} | max={self.max_results}"
            )

            all_results = []
            meta_agg = {
                "competition_count": 0,
                "avg_bsr_values": [],
                "ku_count": 0,
                "total_count": 0,
            }

            for mp_idx, mp in enumerate(self.marketplaces):
                if self.is_cancelled:
                    return
                self.status.emit(f"Searching {mp.upper()} for '{self.seed}'...")
                self.progress.emit(mp_idx, len(self.marketplaces))

                data = search_kindle(
                    keyword=self.seed,
                    marketplace=mp,
                    max_results=self.max_results,
                    sort_by=self.sort_by,
                )

                mp_results = data.get("results", [])
                competition = data.get("competition_count")
                if competition:
                    meta_agg["competition_count"] += competition

                for item in mp_results:
                    item["marketplace"] = mp.upper()
                    item["ku_eligible"] = "✓" if item.get("ku_eligible") else ""
                    item["series"] = item.get("series") or ""
                    item["bsr"] = item.get("bsr") or ""
                    if isinstance(item.get("avg_rating"), float):
                        item["avg_rating"] = f"{item['avg_rating']:.1f}"
                    else:
                        item["avg_rating"] = item.get("avg_rating") or ""
                    bsr_val = data.get("avg_bsr_top10")
                    if bsr_val:
                        meta_agg["avg_bsr_values"].append(bsr_val)
                    all_results.append(item)

                meta_agg["total_count"] += len(mp_results)

            self.progress.emit(len(self.marketplaces), len(self.marketplaces))

            # Renumber positions across marketplaces
            for i, item in enumerate(all_results):
                item["position"] = i + 1

            results = all_results

            # Log summary
            avg_bsr_vals = meta_agg["avg_bsr_values"]
            avg_bsr = round(sum(avg_bsr_vals) / len(avg_bsr_vals)) if avg_bsr_vals else "N/A"
            self.log.emit(
                f"\nTotal results: {len(results)} | "
                f"Competition: {meta_agg['competition_count']} | "
                f"Avg BSR: {avg_bsr}"
            )

        self.log.emit(f"\nTotal results: {len(results)}")
        self.status.emit(f"Found {len(results)} results")
        return {"results": results, "mode": self.mode}


def _columns_for_mode(mode):
    if mode == "kindle_movers":
        return MOVERS_COLUMNS, MOVERS_DISPLAY_NAMES
    elif mode in ("most_wished", "hot_new", "also_bought"):
        return WISHLIST_COLUMNS, WISHLIST_DISPLAY_NAMES
    elif mode == "keyword_search":
        return KEYWORD_SEARCH_COLUMNS, KEYWORD_SEARCH_DISPLAY_NAMES
    else:
        return TRENDING_COLUMNS, TRENDING_DISPLAY_NAMES


class TrendingPage(QWidget):
    """Page for discovering trending keywords and books."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("<h2>📈 Amazon Trending</h2>")
        layout.addWidget(header)

        # ── Row 1: Source selector + mode-specific controls ──────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        source_label = QLabel("Source:")
        toolbar.addWidget(source_label)

        self._mode_combo = QComboBox()
        self._mode_combo.setMinimumWidth(220)
        # Amazon Findings first
        self._mode_combo.addItem("🔍 Amazon Findings",               "keyword_search")
        self._mode_combo.addItem("🏆 Bestsellers – Kindle",         "bestseller:kindle")
        self._mode_combo.addItem("🆓 Bestsellers – Free Kindle",    "bestseller:kindle_free")
        self._mode_combo.addItem("🚀 Movers & Shakers",             "kindle_movers")
        self._mode_combo.addItem("⭐ Hot New Releases",              "hot_new")
        self._mode_combo.addItem("💝 Most Wished For",              "most_wished")
        self._mode_combo.addItem("🔗 Also Bought (by ASIN)",        "also_bought")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self._mode_combo)

        # ── Keyword Search controls (inline, same row) ──────────────
        self._seed_input = QLineEdit()
        self._seed_input.setPlaceholderText("Keyword (e.g., dark romance)")
        self._seed_input.setMinimumWidth(280)
        toolbar.addWidget(self._seed_input)

        self._sort_combo = QComboBox()
        self._sort_combo.setToolTip("Sort order")
        for label, value in SORT_OPTIONS:
            self._sort_combo.addItem(label, value)
        self._sort_combo.setFixedWidth(110)
        toolbar.addWidget(self._sort_combo)

        self._max_spin = QSpinBox()
        self._max_spin.setRange(5, 100)
        self._max_spin.setValue(50)
        self._max_spin.setPrefix("Max ")
        self._max_spin.setToolTip("Max results per marketplace")
        self._max_spin.setFixedWidth(80)
        toolbar.addWidget(self._max_spin)

        # Marketplace multi-select dropdown button
        self._mp_btn = QToolButton()
        self._mp_btn.setText("🌍 US ▾")
        self._mp_btn.setToolTip("Select marketplaces")
        self._mp_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._mp_btn.setMinimumWidth(90)
        self._mp_menu = QMenu(self._mp_btn)
        self._mp_actions = {}
        defaults = {"us"}
        for mp in MARKETPLACES:
            action = self._mp_menu.addAction(mp.upper())
            action.setCheckable(True)
            action.setChecked(mp in defaults)
            action.toggled.connect(self._update_mp_label)
            self._mp_actions[mp] = action
        self._mp_btn.setMenu(self._mp_menu)
        toolbar.addWidget(self._mp_btn)

        # ── Category dropdown (for non-keyword, non-also_bought modes) ──
        self._category_label = QLabel("Category:")
        toolbar.addWidget(self._category_label)

        self._category_combo = QComboBox()
        self._category_combo.setMinimumWidth(160)
        for label, key in AMAZON_CATEGORIES:
            self._category_combo.addItem(label, key)
        toolbar.addWidget(self._category_combo)

        # ASIN input (shown only for also_bought mode)
        self._asin_input = QLineEdit()
        self._asin_input.setPlaceholderText("Enter ASIN (e.g., B09XYZABC1)")
        self._asin_input.setFixedWidth(200)
        self._asin_input.setVisible(False)
        toolbar.addWidget(self._asin_input)

        self._discover_btn = QPushButton("▶ Discover")
        self._discover_btn.setProperty("class", "btn-primary")
        self._discover_btn.clicked.connect(self._on_refresh)
        toolbar.addWidget(self._discover_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Info bar
        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        self._info_label.setProperty("class", "info-text")
        layout.addWidget(self._info_label)
        self._update_info()

        # Data table
        self._table = DataTable()
        layout.addWidget(self._table, 1)

        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

        # Initialize visibility for the default mode (Amazon Findings)
        self._on_mode_changed(0)

    def _on_mode_changed(self, _):
        mode = self._get_mode()
        is_also_bought = mode == "also_bought"
        is_kw_search = mode == "keyword_search"

        # Keyword search controls
        for w in (self._seed_input, self._sort_combo, self._max_spin, self._mp_btn):
            w.setVisible(is_kw_search)

        # Category controls
        self._category_label.setVisible(not is_also_bought and not is_kw_search)
        self._category_combo.setVisible(not is_also_bought and not is_kw_search)

        # ASIN input
        self._asin_input.setVisible(is_also_bought)

        self._update_info()

    def _update_mp_label(self, _=None):
        """Update the marketplace button text to show selected ones."""
        selected = [mp.upper() for mp, act in self._mp_actions.items() if act.isChecked()]
        if not selected:
            self._mp_btn.setText("🌍 None ▾")
        elif len(selected) <= 3:
            self._mp_btn.setText(f"🌍 {', '.join(selected)} ▾")
        else:
            self._mp_btn.setText(f"🌍 {len(selected)} MPs ▾")

    def _update_info(self):
        mode = self._get_mode()
        infos = {

            "bestseller":
                "Scrapes the Amazon Kindle bestseller list (top 100 paid titles).",
            "kindle_movers":
                "Amazon Movers & Shakers is refreshed hourly — shows books climbing "
                "fastest in BSR. Best signal for detecting emerging trends.",
            "hot_new":
                "Hot New Releases shows the top-selling new books published in the "
                "last 30 days. Great for spotting fast-growing niches.",
            "most_wished":
                "Books most frequently added to Amazon Wish Lists — "
                "strong indicator of latent demand not yet converted to sales.",
            "also_bought":
                "Enter a competitor ASIN to see what customers also buy — "
                "maps the niche cluster around any book.",
            "keyword_search":
                "Amazon Findings — search Kindle by keyword, sort by Bestsellers or "
                "New Releases across multiple marketplaces. Great for niche research by topic.",
        }
        self._info_label.setText(infos.get(mode, ""))

    def _get_mode(self):
        raw = self._mode_combo.currentData() or "trending"
        return raw.split(":")[0] if ":" in raw else raw

    def _get_list_type(self):
        raw = self._mode_combo.currentData() or ""
        return raw.split(":")[1] if ":" in raw else ""

    def _on_refresh(self):
        mode = self._get_mode()

        if mode == "also_bought" and not self._asin_input.text().strip():
            QMessageBox.warning(self, "ASIN Required", "Please enter an ASIN.")
            return

        if mode == "keyword_search" and not self._seed_input.text().strip():
            QMessageBox.warning(self, "Keyword Required", "Please enter a seed keyword.")
            return

        if mode == "keyword_search":
            selected_mps = [mp for mp, act in self._mp_actions.items() if act.isChecked()]
            if not selected_mps:
                QMessageBox.warning(self, "Marketplace Required", "Please select at least one marketplace.")
                return

        self._discover_btn.setEnabled(False)
        self._progress.start()

        asin = self._asin_input.text().strip().upper() or None
        list_type = self._get_list_type()

        # Map 'bestseller' mode back to the list_type value
        if mode == "bestseller":
            worker_mode = "bestseller"
        else:
            worker_mode = mode

        category = self._category_combo.currentData() or None

        # Build worker kwargs
        worker_kwargs = dict(
            mode=worker_mode,
            list_type=list_type,
            asin=asin,
            category=category,
        )

        if mode == "keyword_search":
            selected_mps = [mp for mp, act in self._mp_actions.items() if act.isChecked()]
            worker_kwargs.update(
                seed=self._seed_input.text().strip(),
                sort_by=self._sort_combo.currentData(),
                marketplaces=selected_mps,
                max_results=self._max_spin.value(),
            )

        self._worker = TrendingWorker(**worker_kwargs)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, payload):
        self._discover_btn.setEnabled(True)
        mode = payload.get("mode", "trending")
        results = payload.get("results", [])
        count = len(results)

        try:
            source_label = self._mode_combo.currentText()
            if mode == "keyword_search":
                seed = self._seed_input.text().strip()
                sort_label = self._sort_combo.currentText()
                selected_mps = [mp.upper() for mp, act in self._mp_actions.items() if act.isChecked()]
                query_str = f"{seed} [{', '.join(selected_mps)}] {sort_label}"
            else:
                query_str = source_label

            SearchHistory.instance().log(
                tool="Trending", action="Discover",
                query=query_str,
                results=results, result_count=count,
            )
        except Exception:
            pass

        self._progress.finish(f"Found {count} results")

        if results:
            cols, names = _columns_for_mode(mode)
            self._table.load_data(results, cols, names)
        self._worker = None

    def _on_error(self, error_msg: str):
        self._discover_btn.setEnabled(True)
        self._progress.finish(f"Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def focus_search(self):
        self._table.focus_search()
