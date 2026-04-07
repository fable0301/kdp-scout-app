from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QMessageBox
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.asin_input import ASINInput
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.scrape_worker import ReverseASINWorker
from kdp_scout.gui.search_history import SearchHistory


RESULT_COLUMNS = ["keyword", "position", "source", "search_volume"]

RESULT_DISPLAY_NAMES = {
    "keyword": "Keyword",
    "position": "Position",
    "source": "Source",
    "search_volume": "Search Volume",
}


class ASINLookupPage(QWidget):
    """Page for reverse ASIN keyword lookup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("<h2>🔎 ASIN Lookup</h2>")
        layout.addWidget(header)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._asin_input = ASINInput()
        self._asin_input.asin_submitted.connect(self._on_lookup)
        toolbar.addWidget(self._asin_input)

        method_label = QLabel("Method:")
        toolbar.addWidget(method_label)

        self._method_combo = QComboBox()
        self._method_combo.addItems(["Auto", "Probe", "DataForSEO"])
        self._method_combo.setMinimumWidth(120)
        toolbar.addWidget(self._method_combo)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Info
        info = QLabel(
            "Enter an ASIN to discover which keywords that book ranks for. "
            "'Auto' tries the fastest method first. 'Probe' checks Amazon autocomplete positions. "
            "'DataForSEO' uses the API for comprehensive data."
        )
        info.setWordWrap(True)
        info.setProperty("class", "info-text")
        layout.addWidget(info)

        # Results table
        self._table = DataTable()
        layout.addWidget(self._table, 1)

        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

    def _on_lookup(self, asin: str):
        method_map = {
            "Auto": "auto",
            "Probe": "probe",
            "DataForSEO": "dataforseo",
        }
        method = method_map.get(self._method_combo.currentText(), "auto")

        self._asin_input.set_enabled(False)
        self._progress.start()

        self._worker = ReverseASINWorker(asin=asin, method=method)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, result):
        self._asin_input.set_enabled(True)
        count = len(result) if result else 0
        try:
            asin = self._asin_input.text() if hasattr(self._asin_input, 'text') else ''
            SearchHistory.instance().log(
                tool="ASIN Lookup", action="Reverse ASIN",
                query=asin,
                results=result, result_count=count,
            )
        except Exception:
            pass
        self._progress.finish(f"Found {count} keywords")

        if result:
            self._table.load_data(result, RESULT_COLUMNS, RESULT_DISPLAY_NAMES)
        else:
            self._table.clear()
        self._worker = None

    def _on_error(self, error_msg: str):
        self._asin_input.set_enabled(True)
        self._progress.finish(f"Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def focus_search(self):
        self._table.focus_search()
