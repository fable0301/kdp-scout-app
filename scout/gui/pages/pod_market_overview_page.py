from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox,
)
from PyQt6.QtCore import Qt

from scout.gui.widgets.data_table import DataTable
from scout.gui.widgets.progress_panel import ProgressPanel
from scout.gui.workers.pod_workers import PodMarketOverviewWorker
from scout.gui.search_history import SearchHistory


POD_MARKET_COLUMNS = [
    "row_num", "niche", "score", "platform", "source",
]

POD_MARKET_DISPLAY_NAMES = {
    "row_num": "#",
    "niche": "Niche",
    "score": "Score",
    "platform": "Platform",
    "source": "Source",
}


class PodMarketOverviewPage(QWidget):
    """Dashboard view of POD market."""
    
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
        header = QLabel("<h2>📊 POD Market Overview</h2>")
        layout.addWidget(header)
        
        # Auto-load on startup
        self._progress = ProgressPanel(show_log=True)
        layout.addWidget(self._progress)
        
        # Hot niches section
        hot_group = QGroupBox("🔥 Hot Niches")
        hot_layout = QVBoxLayout(hot_group)
        self._hot_table = DataTable()
        hot_layout.addWidget(self._hot_table)
        layout.addWidget(hot_group)
        
        # Rising trends section
        rising_group = QGroupBox("📈 Rising Trends")
        rising_layout = QVBoxLayout(rising_group)
        self._rising_table = DataTable()
        rising_layout.addWidget(self._rising_table)
        layout.addWidget(rising_group)
        
        # Opportunities section
        opp_group = QGroupBox("💡 Opportunities")
        opp_layout = QVBoxLayout(opp_group)
        self._opp_table = DataTable()
        opp_layout.addWidget(self._opp_table)
        layout.addWidget(opp_group, 1)
        
        # Progress (hidden initially)
        self._progress.hide()
        
        # Auto-load
        self._load_overview()
    
    def _load_overview(self):
        self._progress.show()
        self._progress.start()
        
        self._worker = PodMarketOverviewWorker()
        self._worker.status.connect(self._progress.set_status)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_load_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()
    
    def _on_load_finished(self, data):
        self._progress.finish("Market overview loaded!")
        self._worker = None
        
        # Populate tables
        self._hot_data = data.get("hot_niches", [])
        self._populate_table(self._hot_table, self._hot_data)
        
        self._rising_data = [{"niche": t, "score": 0.8, "source": "google"} 
                           for t in data.get("rising_trends", [])]
        self._populate_table(self._rising_table, self._rising_data)
        
        self._opp_data = [{"niche": o.get("keyword", ""), 
                          "score": o.get("demand", 0), 
                          "platform": o.get("platform", "all")}
                         for o in data.get("opportunities", [])]
        self._populate_table(self._opp_table, self._opp_data)
        
        # Hide progress after 2 seconds
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, self._progress.hide)
        try:
            all_results = self._hot_data + self._rising_data + self._opp_data
            SearchHistory.instance().log(
                tool="POD Market Overview", action="load",
                results=all_results, result_count=len(all_results),
            )
        except Exception:
            pass
    
    def _populate_table(self, table, data):
        rows = []
        for i, item in enumerate(data, 1):
            row = {
                "row_num": i,
                "niche": item.get("niche", ""),
                "score": f"{item.get('score', 0):.2f}",
                "platform": item.get("platform", ""),
                "source": item.get("source", ""),
            }
            rows.append(row)
        table.load_data(rows, columns=POD_MARKET_COLUMNS, display_names=POD_MARKET_DISPLAY_NAMES)
    
    def _on_worker_error(self, error_msg):
        self._progress.finish(f"Error: {error_msg}")
        self._worker = None
        
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Error", f"Failed to load market overview:\n{error_msg}")
