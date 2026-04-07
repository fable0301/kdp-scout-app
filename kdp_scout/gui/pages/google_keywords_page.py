"""Google Keywords page — mine keywords via Google Suggest."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QMessageBox, QLineEdit,
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.base_worker import BaseWorker
from kdp_scout.gui.search_history import SearchHistory


COLUMNS = ["keyword", "source", "position"]
DISPLAY_NAMES = {
    "keyword": "Keyword",
    "source": "Source / Query",
    "position": "Position",
}


class GoogleKeywordsWorker(BaseWorker):
    """Worker for Google keyword mining."""

    def __init__(self, mode="mine", seed="", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.seed = seed

    def run_task(self):
        results = []

        if self.mode == "mine":
            if not self.seed:
                raise ValueError("Enter a seed keyword to mine")

            self.status.emit(f"Mining Google Suggest for \"{self.seed}\"...")
            self.log.emit(f"Alphabet crawl + question patterns for: {self.seed}")
            self.log.emit("This may take 1-2 minutes...\n")

            from kdp_scout.collectors.google_suggest import mine_suggest_keywords
            results = mine_suggest_keywords(
                self.seed,
                progress_callback=lambda c, t: (self.progress.emit(c, t),
                                                 self.log.emit(f"  {c}/{t} queries...") if c % 15 == 0 else None),
                cancel_check=lambda: self.is_cancelled,
            )

        elif self.mode == "related":
            if not self.seed:
                raise ValueError("Enter a keyword to find related searches")

            self.status.emit(f"Finding related searches for \"{self.seed}\"...")
            self.log.emit(f"Querying variations: vs, like, similar to, etc.")

            from kdp_scout.collectors.google_suggest import get_related_searches_fast
            results = get_related_searches_fast(
                self.seed,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )

        elif self.mode == "questions":
            if not self.seed:
                raise ValueError("Enter a keyword to find questions")

            self.status.emit(f"Finding questions about \"{self.seed}\"...")
            self.log.emit("Querying question patterns: how, what, why, where, when, can, do, is...")

            from kdp_scout.collectors.google_suggest import query_google_suggest
            question_prefixes = [
                "how to", "what is", "why do", "why is", "where to",
                "when to", "can you", "do you", "is it", "what are",
                "how do", "should i", "how much", "what does",
            ]
            total = len(question_prefixes)
            seen = {}
            for i, prefix in enumerate(question_prefixes):
                if self.is_cancelled:
                    break
                suggestions = query_google_suggest(f"{prefix} {self.seed}")
                for kw, pos in suggestions:
                    kw_lower = kw.strip().lower()
                    if kw_lower not in seen:
                        seen[kw_lower] = True
                        results.append({
                            "keyword": kw.strip(),
                            "source": f"Question: {prefix}...",
                            "position": pos,
                        })
                self.progress.emit(i + 1, total)

        self.log.emit(f"\nTotal results: {len(results)}")
        self.status.emit(f"Found {len(results)} keywords")
        return {"results": results, "mode": self.mode}


class GoogleKeywordsPage(QWidget):
    """Google Keywords mining page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("<h2>\U0001f50d Google Keywords</h2>")
        layout.addWidget(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("Tool:"))

        self._mode_combo = QComboBox()
        self._mode_combo.setMinimumWidth(280)
        self._mode_combo.addItem("⛏ Mine Keywords (alphabet crawl)", "mine")
        self._mode_combo.addItem("🔗 Related Searches", "related")
        self._mode_combo.addItem("❓ People Also Ask (questions)", "questions")
        toolbar.addWidget(self._mode_combo)

        self._seed_input = QLineEdit()
        self._seed_input.setPlaceholderText("Enter seed keyword (e.g., dark romance)")
        self._seed_input.setMinimumWidth(280)
        toolbar.addWidget(self._seed_input)

        self._mine_btn = QPushButton("▶ Mine")
        self._mine_btn.setProperty("class", "btn-primary")
        self._mine_btn.clicked.connect(self._on_mine)
        toolbar.addWidget(self._mine_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._info_label = QLabel(
            "Enter a seed keyword and mine Google Suggest for hundreds of long-tail variations. "
            "Uses alphabet expansion + question patterns. No API key needed."
        )
        self._info_label.setWordWrap(True)
        self._info_label.setProperty("class", "info-text")
        layout.addWidget(self._info_label)

        self._table = DataTable()
        layout.addWidget(self._table, 1)

        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

    def _on_mine(self):
        seed = self._seed_input.text().strip()
        mode = self._mode_combo.currentData() or "mine"

        if not seed:
            QMessageBox.warning(self, "Keyword Required", "Please enter a seed keyword.")
            return

        self._mine_btn.setEnabled(False)
        self._progress.start()

        self._worker = GoogleKeywordsWorker(mode=mode, seed=seed)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, payload):
        self._mine_btn.setEnabled(True)
        results = payload.get("results", [])
        count = len(results)

        try:
            SearchHistory.instance().log(
                tool="Google Keywords", action=self._mode_combo.currentText(),
                query=self._seed_input.text().strip(),
                results=results, result_count=count,
            )
        except Exception:
            pass

        self._progress.finish(f"Found {count} keywords")

        if results:
            self._table.load_data(results, COLUMNS, DISPLAY_NAMES)
        self._worker = None

    def _on_error(self, msg):
        self._mine_btn.setEnabled(True)
        self._progress.finish(f"Error: {msg}")
        QMessageBox.critical(self, "Error", msg)
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def focus_search(self):
        self._table.focus_search()
