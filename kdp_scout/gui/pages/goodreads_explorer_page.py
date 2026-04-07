"""Goodreads Explorer — search Goodreads & Open Library, analyze niches, find gaps."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QMessageBox, QLineEdit,
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.goodreads_worker import GoodreadsWorker
from kdp_scout.gui.search_history import SearchHistory


# -- Column definitions per mode -----------------------------------------------

SEARCH_COLUMNS = ["title", "author", "rating", "ratings_count", "url"]
SEARCH_DISPLAY = {
    "title": "Title",
    "author": "Author",
    "rating": "Rating",
    "ratings_count": "# Ratings",
    "url": "URL",
}

NICHE_COLUMNS = ["title", "author", "rating", "ratings_count", "reviews_count", "want_to_read_count", "shelves"]
NICHE_DISPLAY = {
    "title": "Title",
    "author": "Author",
    "rating": "Rating",
    "ratings_count": "# Ratings",
    "reviews_count": "# Reviews",
    "want_to_read_count": "Want to Read",
    "shelves": "Shelves",
}

OL_COLUMNS = ["title", "author", "first_publish_year", "edition_count", "subject", "ratings_average", "want_to_read_count"]
OL_DISPLAY = {
    "title": "Title",
    "author": "Author",
    "first_publish_year": "Year",
    "edition_count": "Editions",
    "subject": "Subjects",
    "ratings_average": "Avg Rating",
    "want_to_read_count": "Want to Read",
}

SHELVES_COLUMNS = ["name", "books_count", "voters"]
SHELVES_DISPLAY = {
    "name": "List / Shelf",
    "books_count": "Books",
    "voters": "Voters",
}

GAP_COLUMNS = ["title", "author", "gr_rating", "gr_ratings_count", "gr_want_to_read", "opportunity_score"]
GAP_DISPLAY = {
    "title": "Title",
    "author": "Author",
    "gr_rating": "GR Rating",
    "gr_ratings_count": "GR Ratings",
    "gr_want_to_read": "Want to Read",
    "opportunity_score": "Opportunity",
}


class GoodreadsExplorerPage(QWidget):
    """📚 Goodreads Explorer page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("<h2>📚 Goodreads Explorer</h2>")
        layout.addWidget(header)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("Tool:"))

        self._mode_combo = QComboBox()
        self._mode_combo.setMinimumWidth(310)
        self._mode_combo.addItem("🔍 Search Goodreads", "search")
        self._mode_combo.addItem("📊 Niche Analysis", "niche")
        self._mode_combo.addItem("📚 Open Library Search", "open_library")
        self._mode_combo.addItem("🏷 Shelf / Tag Explorer", "shelves")
        self._mode_combo.addItem("🔄 Gap Analysis (GR vs Amazon)", "gap_analysis")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self._mode_combo)

        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("Enter search query or niche keyword")
        self._query_input.setMinimumWidth(300)
        self._query_input.returnPressed.connect(self._on_search)
        toolbar.addWidget(self._query_input)

        self._search_btn = QPushButton("▶ Search")
        self._search_btn.setProperty("class", "btn-primary")
        self._search_btn.clicked.connect(self._on_search)
        toolbar.addWidget(self._search_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Info label
        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        self._info_label.setProperty("class", "info-text")
        layout.addWidget(self._info_label)
        self._update_info()

        # Data table
        self._table = DataTable()
        layout.addWidget(self._table, 1)

        # Progress panel
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

    # -- Mode switching --------------------------------------------------------

    def _on_mode_changed(self, _):
        self._update_info()

    def _update_info(self):
        mode = self._mode_combo.currentData() or "search"
        infos = {
            "search": (
                "Search Goodreads by keyword, title, or author. "
                "Returns books with ratings and review counts scraped from public pages. "
                "Rate-limited to be respectful (1 request per 3 seconds)."
            ),
            "niche": (
                "Analyze a niche on Goodreads: fetches top books, scrapes details, "
                "and computes aggregate metrics including reader demand score, "
                "average want-to-read, common shelves, and publication frequency."
            ),
            "open_library": (
                "Search the Open Library catalog (free API, no key needed). "
                "Returns edition counts, subjects, reader stats (want-to-read, "
                "already-read), and average ratings."
            ),
            "shelves": (
                "Find reader-created Goodreads lists and shelves for a keyword. "
                "Great for discovering sub-niches and how readers categorize books."
            ),
            "gap_analysis": (
                "Cross-reference Goodreads popularity data to spot opportunities. "
                "Books with high want-to-read counts and ratings but potentially "
                "underserved on Amazon are flagged with an opportunity score."
            ),
        }
        self._info_label.setText(infos.get(mode, ""))

    # -- Search ----------------------------------------------------------------

    def _on_search(self):
        query = self._query_input.text().strip()
        mode = self._mode_combo.currentData() or "search"

        if not query:
            QMessageBox.warning(self, "Query Required", "Please enter a search query or keyword.")
            return

        self._search_btn.setEnabled(False)
        self._progress.start()

        self._worker = GoodreadsWorker(mode=mode, query=query, max_books=10)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, payload):
        self._search_btn.setEnabled(True)
        if payload is None:
            self._progress.finish("Cancelled")
            self._worker = None
            return

        mode = payload.get("mode", "search")
        results = payload.get("results", [])
        count = len(results)

        try:
            SearchHistory.instance().log(
                tool="Goodreads",
                action=self._mode_combo.currentText(),
                query=self._query_input.text().strip(),
                results=results,
                result_count=count,
            )
        except Exception:
            pass

        self._progress.finish(f"Found {count} results")

        if results:
            # Flatten list fields for table display
            for r in results:
                for key in ("shelves", "genres"):
                    if key in r and isinstance(r[key], list):
                        r[key] = ", ".join(str(s) for s in r[key][:5])

            if mode == "search":
                self._table.load_data(results, SEARCH_COLUMNS, SEARCH_DISPLAY)
            elif mode == "niche":
                self._table.load_data(results, NICHE_COLUMNS, NICHE_DISPLAY)
            elif mode == "open_library":
                self._table.load_data(results, OL_COLUMNS, OL_DISPLAY)
            elif mode == "shelves":
                self._table.load_data(results, SHELVES_COLUMNS, SHELVES_DISPLAY)
            elif mode == "gap_analysis":
                self._table.load_data(results, GAP_COLUMNS, GAP_DISPLAY)
            else:
                self._table.load_data(results, SEARCH_COLUMNS, SEARCH_DISPLAY)

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
