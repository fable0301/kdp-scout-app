from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QFormLayout, QComboBox, QMessageBox, QLineEdit,
)
from PyQt6.QtCore import Qt

from scout.gui.widgets.data_table import DataTable
from scout.gui.widgets.progress_panel import ProgressPanel
from scout.gui.workers.pod_workers import PodCompetitorsWorker
from scout.gui.search_history import SearchHistory


POD_COMP_COLUMNS = [
    "row_num", "title", "price", "reviews", "seller", "is_bestseller",
]

POD_COMP_DISPLAY_NAMES = {
    "row_num": "#",
    "title": "Title",
    "price": "Price",
    "reviews": "Reviews",
    "seller": "Seller",
    "is_bestseller": "Bestseller",
}


class PodCompetitorsPage(QWidget):
    """Page for analyzing POD competitors in a niche."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._listings = []
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Header
        header = QLabel("<h2>🏷 POD Competitors</h2>")
        layout.addWidget(header)
        
        # Search section
        search_group = QGroupBox("Niche Analysis")
        search_layout = QFormLayout(search_group)
        
        self._niche_input = QLineEdit()
        self._niche_input.setPlaceholderText("Enter a niche or keyword (e.g., cat lover, nurse gift...)")
        search_layout.addRow("Niche:", self._niche_input)
        
        self._platform_combo = QComboBox()
        self._platform_combo.addItems(["Amazon Merch", "Etsy", "Redbubble"])
        search_layout.addRow("Platform:", self._platform_combo)
        
        layout.addWidget(search_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self._analyze_btn = QPushButton("🏷 Analyze Niche")
        self._analyze_btn.setProperty("class", "btn-primary")
        self._analyze_btn.clicked.connect(self._start_analysis)
        btn_layout.addWidget(self._analyze_btn)
        
        btn_layout.addStretch()
        
        self._mine_btn = QPushButton("⛏ Mine These Keywords")
        self._mine_btn.clicked.connect(self._mine_keywords)
        btn_layout.addWidget(self._mine_btn)
        
        layout.addLayout(btn_layout)
        
        # Results table
        self._table = DataTable()
        self._table._model._columns = POD_COMP_COLUMNS
        self._table._model._display_names = POD_COMP_DISPLAY_NAMES
        layout.addWidget(self._table, 1)
        
        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._cancel_worker)
        layout.addWidget(self._progress)
    
    def _start_analysis(self):
        niche = self._niche_input.text().strip()
        if not niche:
            QMessageBox.warning(self, "Input Required", "Please enter a niche to analyze.")
            return
        
        platform = self._platform_combo.currentText().lower()
        if "amazon" in platform:
            platform = "merch"
        elif "etsy" in platform:
            platform = "etsy"
        elif "redbubble" in platform:
            platform = "redbubble"
        
        self._progress.start()
        self._analyze_btn.setEnabled(False)
        
        self._worker = PodCompetitorsWorker(niche, platform)
        self._worker.status.connect(self._progress.set_status)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.log.connect(self._progress.set_status)
        self._worker.finished_with_result.connect(self._on_analysis_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()
    
    def _on_analysis_finished(self, listings):
        self._progress.finish(f"Found {len(listings)} competitors")
        self._analyze_btn.setEnabled(True)
        self._listings = listings
        self._populate_table()
        self._worker = None
        try:
            SearchHistory.instance().log(
                tool="POD Competitors", action="analyze",
                query=self._niche_input.text().strip(),
                results=listings, result_count=len(listings),
            )
        except Exception:
            pass
    
    def _populate_table(self):
        data = []
        for i, listing in enumerate(self._listings, 1):
            row = {
                "row_num": i,
                "title": listing.get("title", ""),
                "price": f"${listing.get('price', 0):.2f}",
                "reviews": listing.get("reviews_count", 0),
                "seller": listing.get("seller", ""),
                "is_bestseller": "✓" if listing.get("is_bestseller") else "",
            }
            data.append(row)
        self._table.load_data(data)
    
    def _mine_keywords(self):
        # Placeholder - will send keywords to pod_keywords_page
        QMessageBox.information(self, "Mine Keywords", "Will send keywords to Keywords page.")
    
    def _cancel_worker(self):
        if self._worker:
            self._worker.cancel()
    
    def _on_worker_error(self, error_msg):
        self._progress.finish(f"Error: {error_msg}")
        self._analyze_btn.setEnabled(True)
        self._worker = None
