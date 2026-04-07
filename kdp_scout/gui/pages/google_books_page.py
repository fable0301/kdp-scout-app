"""Google Books Explorer — search and analyze books via Google Books API."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QMessageBox, QLineEdit,
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.base_worker import BaseWorker
from kdp_scout.gui.search_history import SearchHistory


BOOK_COLUMNS = ["title", "author", "year", "pages", "rating", "ratings_count", "categories", "publisher"]
BOOK_DISPLAY = {
    "title": "Title",
    "author": "Author",
    "year": "Year",
    "pages": "Pages",
    "rating": "Rating",
    "ratings_count": "# Ratings",
    "categories": "Categories",
    "publisher": "Publisher",
}

NICHE_COLUMNS = ["title", "author", "year", "pages", "rating", "is_ebook", "categories"]
NICHE_DISPLAY = {
    "title": "Title",
    "author": "Author",
    "year": "Year",
    "pages": "Pages",
    "rating": "Rating",
    "is_ebook": "eBook?",
    "categories": "Categories",
}


class GoogleBooksWorker(BaseWorker):
    """Worker for Google Books API queries."""

    def __init__(self, mode="search", query="", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.query = query

    def run_task(self):
        from kdp_scout.collectors.google_books import search_books, analyze_niche, get_publication_timeline

        results = []
        metrics = {}

        if self.mode == "search":
            if not self.query:
                raise ValueError("Enter a search query")
            self.status.emit(f"Searching Google Books for \"{self.query}\"...")
            self.log.emit(f"Query: {self.query} (up to 120 results)")
            results = search_books(
                self.query,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )

        elif self.mode == "niche":
            if not self.query:
                raise ValueError("Enter a niche/category to analyze")
            self.status.emit(f"Analyzing niche: \"{self.query}\"...")
            self.log.emit(f"Fetching relevance + newest books for: {self.query}")
            data = analyze_niche(
                self.query,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )
            results = data.get("books", [])
            metrics = data.get("metrics", {})

            if metrics:
                self.log.emit(f"\n── Niche Analysis ──")
                self.log.emit(f"  Total books in niche: {metrics.get('total_books_in_niche', '?')}")
                self.log.emit(f"  Saturation level: {metrics.get('saturation', '?')}")
                self.log.emit(f"  Recent publications (last 2y): {metrics.get('recent_publications', '?')}")
                self.log.emit(f"  Average pages: {metrics.get('avg_pages', '?')}")
                self.log.emit(f"  Average rating: {metrics.get('avg_rating', '?')}")
                self.log.emit(f"  eBooks found: {metrics.get('has_ebooks', '?')}")

        elif self.mode == "timeline":
            if not self.query:
                raise ValueError("Enter a niche/category")
            self.status.emit(f"Fetching publication timeline for \"{self.query}\"...")
            self.log.emit(f"Getting newest books for: {self.query}")
            results = get_publication_timeline(
                self.query,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )

        self.log.emit(f"\nTotal results: {len(results)}")
        self.status.emit(f"Found {len(results)} books")
        return {"results": results, "mode": self.mode, "metrics": metrics}


class GoogleBooksPage(QWidget):
    """Google Books Explorer page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("<h2>📚 Google Books Explorer</h2>")
        layout.addWidget(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("Tool:"))

        self._mode_combo = QComboBox()
        self._mode_combo.setMinimumWidth(280)
        self._mode_combo.addItem("🔍 Search Books", "search")
        self._mode_combo.addItem("📊 Niche Analysis (saturation)", "niche")
        self._mode_combo.addItem("📅 Publication Timeline (newest)", "timeline")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self._mode_combo)

        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("Enter search query or niche (e.g., dark romance)")
        self._query_input.setMinimumWidth(300)
        toolbar.addWidget(self._query_input)

        self._search_btn = QPushButton("▶ Search")
        self._search_btn.setProperty("class", "btn-primary")
        self._search_btn.clicked.connect(self._on_search)
        toolbar.addWidget(self._search_btn)

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

    def _on_mode_changed(self, _):
        self._update_info()

    def _update_info(self):
        mode = self._mode_combo.currentData() or "search"
        infos = {
            "search": "Search Google Books by keyword, title, or author. "
                      "Supports advanced queries: intitle:, inauthor:, subject:. "
                      "Returns up to 120 books with metadata. Free (1000 req/day with API key).",
            "niche": "Analyze a book niche for market saturation. Enter a category "
                     "(e.g., \"dark romance\", \"self help\") to see total books, "
                     "average ratings, recency, and competition level.",
            "timeline": "View the newest books published in a niche, sorted by date. "
                       "Great for spotting emerging trends and measuring publication velocity.",
        }
        self._info_label.setText(infos.get(mode, ""))

    def _on_search(self):
        query = self._query_input.text().strip()
        mode = self._mode_combo.currentData() or "search"

        if not query:
            QMessageBox.warning(self, "Query Required", "Please enter a search query or niche.")
            return

        self._search_btn.setEnabled(False)
        self._progress.start()

        self._worker = GoogleBooksWorker(mode=mode, query=query)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, payload):
        self._search_btn.setEnabled(True)
        mode = payload.get("mode", "search")
        results = payload.get("results", [])
        count = len(results)

        try:
            SearchHistory.instance().log(
                tool="Google Books", action=self._mode_combo.currentText(),
                query=self._query_input.text().strip(),
                results=results, result_count=count,
            )
        except Exception:
            pass

        self._progress.finish(f"Found {count} books")

        if results:
            if mode == "niche":
                self._table.load_data(results, NICHE_COLUMNS, NICHE_DISPLAY)
            else:
                self._table.load_data(results, BOOK_COLUMNS, BOOK_DISPLAY)
        self._worker = None

    def _on_error(self, msg):
        self._search_btn.setEnabled(True)
        self._progress.finish(f"Error: {msg}")
        QMessageBox.critical(self, "Error", msg)
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def focus_search(self):
        self._table.focus_search()
