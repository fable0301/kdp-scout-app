from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QMessageBox, QSplitter, QDialog, QDialogButtonBox, QFrame
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.asin_input import ASINInput
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.scrape_worker import SnapshotWorker
try:
    from kdp_scout.gui.workers.scrape_worker import SnapshotWorkerFast
except ImportError:
    SnapshotWorkerFast = None, AddBookWorker
from kdp_scout.gui.search_history import SearchHistory


BOOK_COLUMNS = [
    "asin", "title", "author", "bsr", "kindle_price", "paperback_price",
    "reviews", "rating", "sales_per_day", "revenue_per_month", "own"
]

BOOK_DISPLAY_NAMES = {
    "asin": "ASIN",
    "title": "Title",
    "author": "Author",
    "bsr": "BSR",
    "kindle_price": "Kindle $",
    "paperback_price": "Paper $",
    "reviews": "Reviews",
    "rating": "Rating",
    "sales_per_day": "Sales/Day",
    "revenue_per_month": "Rev/Mo",
    "own": "Own?",
}


class BSRChartWidget(QFrame):
    """Embedded matplotlib chart showing BSR history."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "chart-frame")
        self.setMinimumHeight(250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        try:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure

            self._figure = Figure(figsize=(8, 3), dpi=100)
            self._figure.patch.set_facecolor('#1e1e2e')
            self._canvas = FigureCanvasQTAgg(self._figure)
            layout.addWidget(self._canvas)
            self._has_matplotlib = True
        except ImportError:
            self._has_matplotlib = False
            label = QLabel("Install matplotlib for BSR charts: pip install matplotlib")
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)

        self._title_label = QLabel("Select a book to view BSR history")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setProperty("class", "chart-title")
        layout.addWidget(self._title_label)

    def plot_bsr_history(self, asin: str, title: str = ""):
        if not self._has_matplotlib:
            return

        self._title_label.setText(f"BSR History: {title or asin}")

        try:
            from kdp_scout.competitor_engine import CompetitorEngine
            engine = CompetitorEngine()
            snapshots = engine.get_snapshots(asin)

            if not snapshots:
                self._title_label.setText(f"No snapshot data for {asin}")
                return

            # Convert sqlite3.Row to dict if needed
            snapshots = [dict(s) if not isinstance(s, dict) else s for s in snapshots]
            dates = [s.get("timestamp", s.get("date", "")) for s in snapshots]
            bsrs = [s.get("bsr", 0) for s in snapshots]

            self._figure.clear()
            ax = self._figure.add_subplot(111)

            # Style the axes
            ax.set_facecolor('#1e1e2e')
            ax.tick_params(colors='#cdd6f4', labelsize=9)
            ax.spines['bottom'].set_color('#45475a')
            ax.spines['left'].set_color('#45475a')
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)

            ax.plot(range(len(bsrs)), bsrs, color='#89b4fa', linewidth=2, marker='o',
                    markersize=4, markerfacecolor='#89b4fa')
            ax.fill_between(range(len(bsrs)), bsrs, alpha=0.15, color='#89b4fa')

            if dates:
                step = max(1, len(dates) // 8)
                ax.set_xticks(range(0, len(dates), step))
                tick_labels = [str(dates[i])[:10] for i in range(0, len(dates), step)]
                ax.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=8)

            ax.set_ylabel('BSR', color='#cdd6f4', fontsize=10)
            ax.invert_yaxis()  # Lower BSR = better
            ax.grid(True, alpha=0.1, color='#585b70')

            self._figure.tight_layout()
            self._canvas.draw()

        except Exception as e:
            self._title_label.setText(f"Error loading chart: {e}")

    def clear_chart(self):
        if self._has_matplotlib:
            self._figure.clear()
            self._canvas.draw()
        self._title_label.setText("Select a book to view BSR history")


class SnapshotHistoryDialog(QDialog):
    """Dialog showing detailed snapshot history for a book."""

    def __init__(self, asin: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Snapshot History: {asin}")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        self._table = DataTable()
        layout.addWidget(self._table)

        try:
            from kdp_scout.competitor_engine import CompetitorEngine
            engine = CompetitorEngine()
            snapshots = engine.get_snapshots(asin)

            if snapshots:
                columns = list(snapshots[0].keys())
                self._table.load_data(snapshots, columns)
        except Exception as e:
            layout.addWidget(QLabel(f"Error loading snapshots: {e}"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)


class CompetitorsPage(QWidget):
    """Page for tracking and analyzing competitor books."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("<h2>🏷 Competitors</h2>")
        layout.addWidget(header)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._asin_input = ASINInput()
        self._asin_input.asin_submitted.connect(self._on_add_book)
        toolbar.addWidget(self._asin_input)

        self._snapshot_btn = QPushButton("📸 Snapshot All")
        self._snapshot_btn.setToolTip("Take snapshots of all tracked books")
        self._snapshot_btn.clicked.connect(self._on_snapshot_all)
        toolbar.addWidget(self._snapshot_btn)

        self._compare_btn = QPushButton("📊 Compare")
        self._compare_btn.setToolTip("Compare tracked books")
        self._compare_btn.clicked.connect(self._on_compare)
        toolbar.addWidget(self._compare_btn)

        self._remove_btn = QPushButton("🗑 Remove")
        self._remove_btn.setProperty("class", "btn-danger")
        self._remove_btn.setToolTip("Remove selected book")
        self._remove_btn.clicked.connect(self._on_remove)
        toolbar.addWidget(self._remove_btn)

        self._refresh_btn = QPushButton("🔄")
        self._refresh_btn.setFixedWidth(40)
        self._refresh_btn.clicked.connect(self._load_data)
        toolbar.addWidget(self._refresh_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Splitter: table on top, chart on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Data table
        self._table = DataTable()
        self._table.selection_changed.connect(self._on_book_selected)
        self._table.row_double_clicked.connect(self._on_book_double_click)
        splitter.addWidget(self._table)

        # BSR Chart
        self._chart = BSRChartWidget()
        splitter.addWidget(self._chart)

        splitter.setSizes([400, 250])
        layout.addWidget(splitter, 1)

        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

    def _load_data(self):
        try:
            from kdp_scout.competitor_engine import CompetitorEngine
            engine = CompetitorEngine()
            books = engine.list_books()

            if books:
                self._table.load_data(books, BOOK_COLUMNS, BOOK_DISPLAY_NAMES)
            else:
                self._table.clear()
        except Exception as e:
            self._progress.set_status(f"Error loading data: {e}")

    def _set_buttons_enabled(self, enabled: bool):
        self._snapshot_btn.setEnabled(enabled)
        self._compare_btn.setEnabled(enabled)
        self._remove_btn.setEnabled(enabled)
        self._asin_input.set_enabled(enabled)

    def _on_add_book(self, asin: str):
        self._set_buttons_enabled(False)
        self._progress.start()

        self._worker = AddBookWorker(asin)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_add_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_add_finished(self, result):
        self._set_buttons_enabled(True)
        self._progress.finish("Book added")
        try:
            SearchHistory.instance().log(
                tool="Competitors", action="Add Book",
                query=str(result) if result else "",
                results=[result] if result else [],
            )
        except Exception:
            pass
        self._asin_input.clear()
        self._load_data()
        self._worker = None

    def _on_snapshot_all(self):
        self._set_buttons_enabled(False)
        self._progress.start()

        self._worker = (SnapshotWorkerFast or SnapshotWorker)()
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_snapshot_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_snapshot_finished(self, result):
        self._set_buttons_enabled(True)
        count = len(result) if result else 0
        try:
            SearchHistory.instance().log(
                tool="Competitors", action="Snapshot All",
                results=result, result_count=count,
            )
        except Exception:
            pass
        self._progress.finish(f"Snapshots complete: {count} books updated")
        self._load_data()
        self._worker = None

    def _on_compare(self):
        try:
            from kdp_scout.reporting import ReportingEngine
            engine = ReportingEngine()
            comparison = engine.competitor_summary()

            if comparison:
                dialog = QDialog(self)
                dialog.setWindowTitle("Competitor Comparison")
                dialog.setMinimumSize(800, 500)
                dlg_layout = QVBoxLayout(dialog)

                table = DataTable()
                if isinstance(comparison, list) and comparison:
                    columns = list(comparison[0].keys())
                    table.load_data(comparison, columns)
                dlg_layout.addWidget(table)

                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
                buttons.rejected.connect(dialog.close)
                dlg_layout.addWidget(buttons)

                dialog.exec()
            else:
                QMessageBox.information(self, "Compare", "No comparison data available. Add some books first.")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_remove(self):
        row_data = self._table.get_selected_row()
        if not row_data:
            QMessageBox.information(self, "Remove", "Please select a book to remove.")
            return

        asin = row_data.get("asin", "")
        title = row_data.get("title", asin)

        reply = QMessageBox.question(
            self, "Remove Book",
            f"Remove '{title}' ({asin}) from tracking?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                from kdp_scout.competitor_engine import CompetitorEngine
                engine = CompetitorEngine()
                engine.remove_book(asin)
                self._load_data()
                self._chart.clear_chart()
                self._progress.set_status(f"Removed {asin}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _on_book_selected(self, row_data: dict):
        asin = row_data.get("asin", "")
        title = row_data.get("title", "")
        if asin:
            self._chart.plot_bsr_history(asin, title)

    def _on_book_double_click(self, row_data: dict):
        asin = row_data.get("asin", "")
        if asin:
            dialog = SnapshotHistoryDialog(asin, self)
            dialog.exec()

    def _on_worker_error(self, error_msg: str):
        self._set_buttons_enabled(True)
        self._progress.finish(f"Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def focus_search(self):
        self._table.focus_search()
