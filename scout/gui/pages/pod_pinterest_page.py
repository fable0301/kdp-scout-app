from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QFormLayout, QComboBox, QMessageBox, QLineEdit,
)
from PyQt6.QtCore import Qt

from scout.gui.widgets.data_table import DataTable
from scout.gui.widgets.progress_panel import ProgressPanel
from scout.gui.workers.pod_workers import PodPinterestWorker
from scout.gui.search_history import SearchHistory


POD_PINTEREST_COLUMNS = [
    "row_num", "suggestion", "frequency", "board_name", "followers", "source",
]

POD_PINTEREST_DISPLAY_NAMES = {
    "row_num": "#",
    "suggestion": "Suggestion",
    "frequency": "Frequency",
    "board_name": "Board",
    "followers": "Followers",
    "source": "Source",
}


class PodPinterestPage(QWidget):
    """Page for exploring Pinterest for POD."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._data = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("<h2>📌 Pinterest Explorer</h2>")
        layout.addWidget(header)

        # Controls
        control_group = QGroupBox("Search Parameters")
        control_layout = QFormLayout(control_group)

        self._seed_input = QLineEdit()
        self._seed_input.setPlaceholderText("Enter a seed keyword...")
        control_layout.addRow("Seed:", self._seed_input)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["All", "Suggest", "Boards", "Trending"])
        control_layout.addRow("Mode:", self._mode_combo)

        layout.addWidget(control_group)

        # Buttons
        btn_layout = QHBoxLayout()

        self._explore_btn = QPushButton("📌 Explore Pinterest")
        self._explore_btn.setProperty("class", "btn-primary")
        self._explore_btn.clicked.connect(self._start_explore)
        btn_layout.addWidget(self._explore_btn)

        btn_layout.addStretch()

        self._analyze_btn = QPushButton("🔬 Analyze Niche")
        self._analyze_btn.clicked.connect(self._analyze_niche)
        btn_layout.addWidget(self._analyze_btn)

        self._export_btn = QPushButton("📤 Export CSV")
        self._export_btn.clicked.connect(self._export_csv)
        btn_layout.addWidget(self._export_btn)

        layout.addLayout(btn_layout)

        # Results table
        self._table = DataTable()
        self._table._model._columns = POD_PINTEREST_COLUMNS
        self._table._model._display_names = POD_PINTEREST_DISPLAY_NAMES
        layout.addWidget(self._table, 1)

        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._cancel_worker)
        layout.addWidget(self._progress)

    def _start_explore(self):
        seed = self._seed_input.text().strip()
        if not seed:
            QMessageBox.warning(self, "Input Required", "Please enter a seed keyword.")
            return

        mode = self._mode_combo.currentText().lower()

        self._progress.start()
        self._explore_btn.setEnabled(False)

        self._worker = PodPinterestWorker(seed, mode=mode)
        self._worker.status.connect(self._progress.set_status)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.log.connect(self._progress.set_status)
        self._worker.finished_with_result.connect(self._on_explore_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_explore_finished(self, result):
        self._progress.finish("Exploration complete!")
        self._explore_btn.setEnabled(True)

        # Combine suggestions, boards, trending into table
        self._data = []
        seen = set()

        # Suggestions
        for sug in result.get("suggestions", []):
            if sug["suggestion"] not in seen:
                seen.add(sug["suggestion"])
                self._data.append({
                    "suggestion": sug["suggestion"],
                    "frequency": sug.get("frequency", 0),
                    "source": "suggest",
                })

        # Boards
        for board in result.get("boards", []):
            self._data.append({
                "suggestion": board.get("board_name", ""),
                "board_name": board.get("board_name", ""),
                "followers": board.get("followers", 0),
                "source": "boards",
            })

        # Trending
        for trend in result.get("trending", []):
            if trend["trend"] not in seen:
                seen.add(trend["trend"])
                self._data.append({
                    "suggestion": trend["trend"],
                    "source": "trending",
                })

        self._populate_table()
        self._worker = None
        try:
            SearchHistory.instance().log(
                tool="POD Pinterest", action="explore",
                query=f"{self._seed_input.text().strip()} [{self._mode_combo.currentText()}]",
                results=self._data, result_count=len(self._data),
            )
        except Exception:
            pass

    def _populate_table(self):
        data = []
        for i, item in enumerate(self._data, 1):
            row = {
                "row_num": i,
                "suggestion": item.get("suggestion", ""),
                "frequency": item.get("frequency", ""),
                "board_name": item.get("board_name", ""),
                "followers": item.get("followers", ""),
                "source": item.get("source", ""),
            }
            data.append(row)
        self._table.load_data(data)

    def _analyze_niche(self):
        row = self._table.get_selected_row()
        if not row:
            QMessageBox.information(
                self, "Select a Niche",
                "Please select a row from the table first."
            )
            return
        niche = row.get("suggestion", "").strip()
        if not niche:
            QMessageBox.information(
                self, "No Niche",
                "No niche keyword found in the selected row."
            )
            return
        mw = self.window()
        if hasattr(mw, '_switch_page'):
            mw._switch_page("Niche Analyzer")
            current = mw._stack.currentWidget()
            if hasattr(current, '_niche_input'):
                current._niche_input.setText(niche)
                current._start_analysis()

    def _export_csv(self):
        if not self._data:
            QMessageBox.warning(self, "No Data", "Nothing to export.")
            return

        from PyQt6.QtWidgets import QFileDialog
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "pinterest_data.csv", "CSV Files (*.csv)"
        )
        if filepath:
            import csv
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=POD_PINTEREST_COLUMNS)
                writer.writeheader()
                for item in self._data:
                    row = {col: item.get(col, "") for col in POD_PINTEREST_COLUMNS}
                    writer.writerow(row)
            QMessageBox.information(self, "Export Complete", f"Exported to {filepath}")

    def _cancel_worker(self):
        if self._worker:
            self._worker.cancel()

    def _on_worker_error(self, error_msg):
        self._progress.finish(f"Error: {error_msg}")
        self._explore_btn.setEnabled(True)
        self._worker = None
