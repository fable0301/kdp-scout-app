"""Google Trending page — discover trending book keywords via Google."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QMessageBox, QLineEdit,
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.base_worker import BaseWorker
from kdp_scout.gui.search_history import SearchHistory


SUGGEST_COLUMNS = ["keyword", "source", "position"]
SUGGEST_DISPLAY = {
    "keyword": "Keyword",
    "source": "Source",
    "position": "Position",
}

TRENDS_COLUMNS = ["query", "value", "source"]
TRENDS_DISPLAY = {
    "query": "Search Term",
    "value": "Interest / Change",
    "source": "Source",
}


class GoogleTrendingWorker(BaseWorker):
    """Worker for Google trending discovery."""

    def __init__(self, mode="suggest", keyword="", custom_seeds=None,
                 niche_keywords=None, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.keyword = keyword
        self.custom_seeds = custom_seeds    # list[str] or None — for suggest mode
        self.niche_keywords = niche_keywords  # list[str] or None — for trending_now mode

    def run_task(self):
        results = []

        if self.mode == "suggest":
            self.status.emit("Discovering trending keywords via Google Suggest...")
            self.log.emit("Scanning categories + KDP niches via Google Autocomplete")
            self.log.emit("This may take 2-3 minutes...\n")

            if self.custom_seeds:
                self.log.emit(f"Custom seeds: {', '.join(self.custom_seeds)}")
            else:
                self.log.emit("Using default KDP categories + niches")

            try:
                from kdp_scout.collectors.google_suggest import discover_trending_suggest_fast
                raw = discover_trending_suggest_fast(
                    custom_seeds=self.custom_seeds,
                    progress_callback=lambda c, t: (self.progress.emit(c, t),
                                                     self.log.emit(f"  {c}/{t} queries...") if c % 20 == 0 else None),
                    cancel_check=lambda: self.is_cancelled,
                )
            except ImportError:
                from kdp_scout.collectors.google_suggest import discover_trending_suggest
                raw = discover_trending_suggest(
                    custom_seeds=self.custom_seeds,
                    progress_callback=lambda c, t: self.progress.emit(c, t),
                    cancel_check=lambda: self.is_cancelled,
                )
            if self.is_cancelled:
                return {"results": [], "mode": self.mode}

            for kw, pos in raw:
                results.append({
                    "keyword": kw,
                    "source": "Google Suggest",
                    "position": str(pos),
                })

        elif self.mode == "related_queries":
            if not self.keyword:
                raise ValueError("Enter a keyword to find related queries")

            self.status.emit(f"Fetching Google Trends related queries for \"{self.keyword}\"...")
            self.log.emit(f"Querying Google Trends API (cat=Books & Literature)")

            from kdp_scout.collectors.google_trends import get_related_queries, has_pytrends
            if not has_pytrends():
                self.log.emit("pytrends not installed — install with: pip install pytrends")
                self.log.emit("Falling back to Google Suggest related searches...\n")
                from kdp_scout.collectors.google_suggest import get_related_searches
                raw = get_related_searches(
                    self.keyword,
                    progress_callback=lambda c, t: self.progress.emit(c, t),
                    cancel_check=lambda: self.is_cancelled,
                )
                for item in raw:
                    results.append({
                        "query": item["keyword"],
                        "value": str(item["position"]),
                        "source": item["source"],
                    })
            else:
                data = get_related_queries(self.keyword)
                for item in data.get("rising", []):
                    results.append({
                        "query": str(item.get("query", "")),
                        "value": str(item.get("value", "")) + " (rising)",
                        "source": "Google Trends Rising",
                    })
                for item in data.get("top", []):
                    results.append({
                        "query": str(item.get("query", "")),
                        "value": str(item.get("value", "")),
                        "source": "Google Trends Top",
                    })
                self.progress.emit(1, 1)

        elif self.mode == "trending_now":
            self.status.emit("Fetching today's trending searches...")
            self.log.emit("Getting real-time trending searches from Google Trends RSS")
            self.log.emit("+ Enriching top trends with book-related suggestions...\n")

            if self.niche_keywords:
                self.log.emit(f"Niche filter: {', '.join(self.niche_keywords)}")
            from kdp_scout.collectors.google_trends import get_trending_book_searches
            raw = get_trending_book_searches(
                geo="US",
                niche_keywords=self.niche_keywords,
                progress_callback=lambda c, t: (
                    self.progress.emit(c, t),
                    self.log.emit(f"  Enriching {c}/{t}...") if c % 5 == 0 else None,
                ),
                cancel_check=lambda: self.is_cancelled,
            )
            if self.is_cancelled:
                return {"results": [], "mode": self.mode}
            for item in raw:
                results.append({
                    "query": item["query"],
                    "value": item.get("traffic", ""),
                    "source": item.get("source", "Google Trending Now"),
                })

        elif self.mode == "related_topics":
            if not self.keyword:
                raise ValueError("Enter a keyword to find related topics")

            self.status.emit(f"Fetching related topics for \"{self.keyword}\"...")

            from kdp_scout.collectors.google_trends import get_related_topics, has_pytrends
            if not has_pytrends():
                self.log.emit("pytrends not installed — install with: pip install pytrends")
                raise ValueError("pytrends package required for Related Topics. Install: pip install pytrends")
            data = get_related_topics(self.keyword)
            for item in data.get("rising", []):
                title = item.get("topic_title", str(item.get("value", "")))
                results.append({
                    "query": title,
                    "value": str(item.get("formattedValue", item.get("value", ""))) + " (rising)",
                    "source": "Related Topics Rising",
                })
            for item in data.get("top", []):
                title = item.get("topic_title", str(item.get("value", "")))
                results.append({
                    "query": title,
                    "value": str(item.get("formattedValue", item.get("value", ""))),
                    "source": "Related Topics Top",
                })
            self.progress.emit(1, 1)

        self.log.emit(f"\nTotal results: {len(results)}")
        self.status.emit(f"Found {len(results)} results")
        return {"results": results, "mode": self.mode}


class GoogleTrendingPage(QWidget):
    """Google Trending discovery page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("<h2>📈 Google Trending</h2>")
        layout.addWidget(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("Tool:"))

        self._mode_combo = QComboBox()
        self._mode_combo.setMinimumWidth(280)
        self._mode_combo.addItem("🌐 Google Suggest (Auto-discover)", "suggest")
        self._mode_combo.addItem("🔥 Trending Now (Today)", "trending_now")
        self._mode_combo.addItem("🔗 Related Queries (by keyword)", "related_queries")
        self._mode_combo.addItem("💡 Related Topics (by keyword)", "related_topics")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self._mode_combo)

        # Keyword input for related_queries / related_topics
        self._keyword_input = QLineEdit()
        self._keyword_input.setPlaceholderText("Enter keyword (e.g., dark romance)")
        self._keyword_input.setFixedWidth(250)
        self._keyword_input.setVisible(False)
        toolbar.addWidget(self._keyword_input)

        # Custom seeds for suggest mode
        self._seeds_label = QLabel("Seeds:")
        self._seeds_label.setVisible(False)
        toolbar.addWidget(self._seeds_label)

        self._seeds_input = QLineEdit()
        self._seeds_input.setPlaceholderText("e.g. dark romance, cozy mystery (optional)")
        self._seeds_input.setFixedWidth(280)
        self._seeds_input.setVisible(False)
        toolbar.addWidget(self._seeds_input)

        # Niche filter for trending_now mode
        self._niche_label = QLabel("Niche filter:")
        self._niche_label.setVisible(False)
        toolbar.addWidget(self._niche_label)

        self._niche_input = QLineEdit()
        self._niche_input.setPlaceholderText("e.g. romance, self help (optional)")
        self._niche_input.setFixedWidth(240)
        self._niche_input.setVisible(False)
        toolbar.addWidget(self._niche_input)

        self._discover_btn = QPushButton("▶ Discover")
        self._discover_btn.setProperty("class", "btn-primary")
        self._discover_btn.clicked.connect(self._on_discover)
        toolbar.addWidget(self._discover_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        self._info_label.setProperty("class", "info-text")
        layout.addWidget(self._info_label)
        self._update_info()

        self._table = DataTable()
        layout.addWidget(self._table, 1)

        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

        # Initialize visibility for default mode (Google Suggest)
        self._on_mode_changed(0)

    def _on_mode_changed(self, _):
        mode = self._mode_combo.currentData() or "suggest"
        needs_kw = mode in ("related_queries", "related_topics")
        needs_seeds = mode == "suggest"
        needs_niche = mode == "trending_now"
        self._keyword_input.setVisible(needs_kw)
        self._seeds_label.setVisible(needs_seeds)
        self._seeds_input.setVisible(needs_seeds)
        self._niche_label.setVisible(needs_niche)
        self._niche_input.setVisible(needs_niche)
        self._update_info()

    def _update_info(self):
        mode = self._mode_combo.currentData() or "suggest"
        infos = {
            "suggest": "Scans default KDP categories + niches via Google Autocomplete. "
                       "Enter custom seeds to focus on specific niches (comma-separated). "
                       "~100+ queries, takes 2-3 minutes. No API key needed.",
            "trending_now": "Shows today's real-time trending searches from Google Trends RSS. "
                           "Use 'Niche filter' to keep only trends matching your keywords "
                           "and orient the Suggest enrichment.",
            "related_queries": "Enter a keyword to find related search queries from Google Trends. "
                              "Shows both \u201crising\u201d (breakout) and \u201ctop\u201d queries. "
                              "Falls back to Suggest if pytrends not installed.",
            "related_topics": "Enter a keyword to discover related topics and subtopics. "
                             "Requires pytrends package.",
        }
        self._info_label.setText(infos.get(mode, ""))

    def _on_discover(self):
        mode = self._mode_combo.currentData() or "suggest"
        keyword = self._keyword_input.text().strip()

        if mode in ("related_queries", "related_topics") and not keyword:
            QMessageBox.warning(self, "Keyword Required", "Please enter a keyword.")
            return

        # Parse custom seeds (comma-separated)
        custom_seeds = None
        raw_seeds = self._seeds_input.text().strip()
        if mode == "suggest" and raw_seeds:
            custom_seeds = [s.strip() for s in raw_seeds.split(",") if s.strip()]

        # Parse niche keywords (comma-separated)
        niche_keywords = None
        raw_niche = self._niche_input.text().strip()
        if mode == "trending_now" and raw_niche:
            niche_keywords = [s.strip() for s in raw_niche.split(",") if s.strip()]

        self._discover_btn.setEnabled(False)
        self._progress.start()

        self._worker = GoogleTrendingWorker(
            mode=mode, keyword=keyword,
            custom_seeds=custom_seeds,
            niche_keywords=niche_keywords,
        )
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, payload):
        self._discover_btn.setEnabled(True)
        if payload is None:
            # Cancelled
            self._progress.finish("Cancelled")
            self._worker = None
            return
        mode = payload.get("mode", "suggest")
        results = payload.get("results", [])
        count = len(results)

        try:
            SearchHistory.instance().log(
                tool="Google Trending", action="Discover",
                query=self._mode_combo.currentText(),
                results=results, result_count=count,
            )
        except Exception:
            pass

        self._progress.finish(f"Found {count} results")

        if results:
            if mode == "suggest":
                self._table.load_data(results, SUGGEST_COLUMNS, SUGGEST_DISPLAY)
            else:
                self._table.load_data(results, TRENDS_COLUMNS, TRENDS_DISPLAY)
        self._worker = None

    def _on_error(self, msg):
        self._discover_btn.setEnabled(True)
        self._progress.finish(f"Error: {msg}")
        QMessageBox.critical(self, "Error", msg)
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def focus_search(self):
        self._table.focus_search()
