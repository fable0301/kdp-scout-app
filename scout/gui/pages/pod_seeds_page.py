from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QFormLayout, QComboBox, QMessageBox, QSpinBox,
)
from PyQt6.QtCore import Qt

from scout.gui.widgets.data_table import DataTable
from scout.gui.widgets.progress_panel import ProgressPanel
from scout.gui.workers.pod_workers import PodSeedsWorker
from scout.gui.search_history import SearchHistory


POD_SEEDS_COLUMNS = [
    "row_num", "seed", "trend_score", "pinterest_pins", "category", "source",
]

POD_SEEDS_DISPLAY_NAMES = {
    "row_num": "#",
    "seed": "Seed Keyword",
    "trend_score": "Trend Score",
    "pinterest_pins": "Pinterest Pins",
    "category": "Category",
    "source": "Source",
}


class PodSeedsPage(QWidget):
    """Page for generating POD seeds enriched with Pinterest trend scores."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._keywords_data = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("<h2>🌱 POD Seeds</h2>")
        layout.addWidget(header)

        desc = QLabel(
            "Generate seed keywords and enrich them with Pinterest trend data. "
            "Higher Trend Score = more Pinterest buzz."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(desc)

        # Category selector
        category_group = QGroupBox("Generate Seeds")
        category_layout = QFormLayout(category_group)

        self._category_combo = QComboBox()
        self._category_combo.addItems([
            "All", "Professions", "Animals", "Family",
            "Hobbies", "Humor", "Holidays", "Sports",
            "Geographic", "Lifestyle",
        ])
        category_layout.addRow("Category:", self._category_combo)

        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(5, 50)
        self._limit_spin.setValue(10)
        category_layout.addRow("Limit per category:", self._limit_spin)

        layout.addWidget(category_group)

        # Buttons
        btn_layout = QHBoxLayout()

        self._generate_btn = QPushButton("🌱 Generate + Score Seeds")
        self._generate_btn.setProperty("class", "btn-primary")
        self._generate_btn.clicked.connect(self._generate_seeds)
        btn_layout.addWidget(self._generate_btn)

        btn_layout.addStretch()

        self._analyze_btn = QPushButton("🔬 Analyze Niche")
        self._analyze_btn.setEnabled(False)
        self._analyze_btn.clicked.connect(self._analyze_niche)
        btn_layout.addWidget(self._analyze_btn)

        self._send_btn = QPushButton("⛏ Send to Keywords")
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._send_to_keywords)
        btn_layout.addWidget(self._send_btn)

        layout.addLayout(btn_layout)

        # Results table
        self._table = DataTable()
        self._table._model._columns = POD_SEEDS_COLUMNS
        self._table._model._display_names = POD_SEEDS_DISPLAY_NAMES
        layout.addWidget(self._table, 1)

        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._cancel_worker)
        layout.addWidget(self._progress)

    def _generate_seeds(self):
        category = self._category_combo.currentText().lower()
        limit = self._limit_spin.value()

        self._progress.start()
        self._generate_btn.setEnabled(False)
        self._analyze_btn.setEnabled(False)
        self._send_btn.setEnabled(False)

        if self._worker:
            if self._worker.isRunning():
                self._worker.quit()
                self._worker.wait(1000)
            self._worker.deleteLater()
            self._worker = None

        self._worker = PodSeedsWorker(category=category, limit_per_category=limit)
        self._worker.status.connect(self._progress.set_status)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.log.connect(self._progress.set_status)
        self._worker.finished_with_result.connect(self._on_generation_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_generation_finished(self, results):
        self._progress.finish(f"Generated {len(results)} enriched seeds")
        self._generate_btn.setEnabled(True)
        self._keywords_data = results

        if results:
            self._populate_table()
            self._analyze_btn.setEnabled(True)
            self._send_btn.setEnabled(True)
        else:
            self._table.load_data([])
            self._progress.set_status("No seeds generated. Try a different category.")

        self._worker = None
        try:
            SearchHistory.instance().log(
                tool="POD Seeds", action="generate",
                query=f"category={self._category_combo.currentText()} limit={self._limit_spin.value()}",
                results=results, result_count=len(results),
            )
        except Exception:
            pass

    def _populate_table(self):
        data = []
        for i, kw in enumerate(self._keywords_data, 1):
            row = {
                "row_num": i,
                "seed": kw.get("seed", ""),
                "trend_score": f"{kw.get('trend_score', 0):.1f}",
                "pinterest_pins": kw.get("pinterest_pins", 0),
                "category": kw.get("category", ""),
                "source": kw.get("source", ""),
            }
            data.append(row)
        self._table.load_data(data)

    def _send_to_keywords(self):
        row = self._table.get_selected_row()
        if not row:
            QMessageBox.information(
                self, "Select a Seed",
                "Please select a seed from the table first."
            )
            return
        seed = row.get("seed", "").strip()
        if not seed:
            return
        mw = self.window()
        if hasattr(mw, '_switch_page'):
            mw._switch_page("Keywords")
            current = mw._stack.currentWidget()
            if hasattr(current, '_seed_input'):
                current._seed_input.setText(seed)
            if hasattr(current, '_start_mine'):
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(500, current._start_mine)

    def _analyze_niche(self):
        row = self._table.get_selected_row()
        if not row:
            QMessageBox.information(
                self, "Select a Seed",
                "Please select a seed from the table first."
            )
            return
        niche = row.get("seed", "").strip()
        if not niche:
            return
        mw = self.window()
        if hasattr(mw, '_switch_page'):
            mw._switch_page("Niche Analyzer")
            current = mw._stack.currentWidget()
            if hasattr(current, '_niche_input'):
                current._niche_input.setText(niche)
                current._start_analysis()

    def _cancel_worker(self):
        if self._worker:
            self._worker.cancel()

    def _on_worker_error(self, error_msg):
        self._progress.finish(f"Error: {error_msg}")
        self._generate_btn.setEnabled(True)
        self._worker = None
