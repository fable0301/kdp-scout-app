from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QGroupBox, QFormLayout,
)
from PyQt6.QtCore import Qt

from scout.gui.widgets.data_table import DataTable
from scout.gui.widgets.progress_panel import ProgressPanel
from scout.gui.workers.pod_workers import PodTrendingWorker
from scout.gui.search_history import SearchHistory


POD_TRENDING_COLUMNS = [
    "row_num", "niche", "score", "platform", "reddit_posts", "g_trends", "pinterest_pins", "source",
]

POD_TRENDING_DISPLAY_NAMES = {
    "row_num": "#",
    "niche": "Niche",
    "score": "Score",
    "platform": "Platform",
    "reddit_posts": "Reddit Posts",
    "g_trends": "G.Trends",
    "pinterest_pins": "Pinterest",
    "source": "Source",
}


class PodTrendingPage(QWidget):
    """Page for POD trending keywords."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._trends_data = []
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Header
        header = QLabel("<h2>📈 POD Trending</h2>")
        layout.addWidget(header)
        
        # Controls
        control_group = QGroupBox("Trending Parameters")
        control_layout = QFormLayout(control_group)
        
        self._category_combo = QComboBox()
        self._category_combo.addItems([
            "All", "Professions", "Animals", "Family", "Hobbies", 
            "Humor", "Holidays", "Sports", "Geographic", "Lifestyle"
        ])
        control_layout.addRow("Category:", self._category_combo)
        
        self._period_combo = QComboBox()
        self._period_combo.addItems(["Today", "7 days", "30 days", "90 days"])
        control_layout.addRow("Period:", self._period_combo)
        
        self._source_combo = QComboBox()
        self._source_combo.addItems(["Reddit + Google", "Pinterest", "Multi-source"])
        control_layout.addRow("Source:", self._source_combo)
        
        layout.addWidget(control_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self._analyze_btn = QPushButton("📈 Analyze Trends")
        self._analyze_btn.setProperty("class", "btn-primary")
        self._analyze_btn.clicked.connect(self._start_analysis)
        btn_layout.addWidget(self._analyze_btn)
        
        btn_layout.addStretch()
        
        self._export_btn = QPushButton("📤 Export CSV")
        self._export_btn.clicked.connect(self._export_csv)
        btn_layout.addWidget(self._export_btn)
        
        layout.addLayout(btn_layout)
        
        # Results table
        self._table = DataTable()
        self._table._model._columns = POD_TRENDING_COLUMNS
        self._table._model._display_names = POD_TRENDING_DISPLAY_NAMES
        layout.addWidget(self._table, 1)
        
        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._cancel_worker)
        layout.addWidget(self._progress)
    
    def _start_analysis(self):
        category = self._category_combo.currentText()
        period = self._period_combo.currentText()
        source = self._source_combo.currentText()
        
        self._progress.start()
        self._analyze_btn.setEnabled(False)
        
        period_map = {"Today": 1, "7 days": 7, "30 days": 30, "90 days": 90}
        period = period_map.get(self._period_combo.currentText(), 30)
        category = self._category_combo.currentText().lower()
        self._worker = PodTrendingWorker(period_days=period, category=category)
        self._worker.status.connect(self._progress.set_status)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.log.connect(self._progress.set_status)
        self._worker.finished_with_result.connect(self._on_analysis_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()
    
    def _on_analysis_finished(self, trends):
        self._progress.finish(f"Found {len(trends)} trends")
        self._analyze_btn.setEnabled(True)
        self._trends_data = trends
        self._populate_table()
        self._worker = None
        try:
            SearchHistory.instance().log(
                tool="POD Trending", action="discover",
                query=f"{self._category_combo.currentText()}/{self._period_combo.currentText()}",
                results=trends, result_count=len(trends),
            )
        except Exception:
            pass
    
    def _populate_table(self):
        data = []
        for i, trend in enumerate(self._trends_data, 1):
            row = {
                "row_num": i,
                "niche": trend.get("niche", ""),
                "score": f"{trend.get('score', 0):.2f}",
                "platform": trend.get("platform", ""),
                "reddit_posts": trend.get("reddit_posts", 0),
                "g_trends": f"{trend.get('g_trends', 0):.1f}",
                "pinterest_pins": trend.get("pinterest_pins", 0),
                "source": trend.get("source", ""),
            }
            data.append(row)
        self._table.load_data(data)
    
    def _export_csv(self):
        if not self._trends_data:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Data", "Nothing to export.")
            return
        
        from PyQt6.QtWidgets import QFileDialog
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "pod_trends.csv", "CSV Files (*.csv)"
        )
        if filepath:
            import csv
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=POD_TRENDING_COLUMNS)
                writer.writeheader()
                for trend in self._trends_data:
                    row = {col: trend.get(col, "") for col in POD_TRENDING_COLUMNS}
                    writer.writerow(row)
            
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Export Complete", f"Exported to {filepath}")
    
    def _cancel_worker(self):
        if self._worker:
            self._worker.cancel()
    
    def _on_worker_error(self, error_msg):
        from PyQt6.QtWidgets import QMessageBox
        self._progress.finish(f"Error: {error_msg}")
        self._analyze_btn.setEnabled(True)
        self._worker = None
