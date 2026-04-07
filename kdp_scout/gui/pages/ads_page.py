import csv
import os
from typing import List, Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTabWidget, QFileDialog, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.base_worker import BaseWorker
from kdp_scout.gui.search_history import SearchHistory


# Common Amazon Ads CSV column name mappings
AMAZON_ADS_COLUMN_MAP = {
    "Customer Search Term": "search_term",
    "Search term": "search_term",
    "search_term": "search_term",
    "Keyword": "keyword",
    "Match Type": "match_type",
    "match_type": "match_type",
    "Impressions": "impressions",
    "impressions": "impressions",
    "Clicks": "clicks",
    "clicks": "clicks",
    "Click-Thru Rate (CTR)": "ctr",
    "CTR": "ctr",
    "Spend": "spend",
    "spend": "spend",
    "Cost Per Click (CPC)": "cpc",
    "CPC": "cpc",
    "Orders": "orders",
    "14 Day Total Orders (#)": "orders",
    "orders": "orders",
    "Sales": "sales",
    "14 Day Total Sales": "sales",
    "sales": "sales",
    "ACoS": "acos",
    "Total Advertising Cost of Sales (ACoS)": "acos",
    "acos": "acos",
    "Campaign Name": "campaign",
    "campaign_name": "campaign",
    "Ad Group Name": "ad_group",
    "ad_group_name": "ad_group",
}


SEARCH_TERM_COLUMNS = [
    "search_term", "impressions", "clicks", "ctr", "spend", "cpc",
    "orders", "sales", "acos"
]

SEARCH_TERM_DISPLAY = {
    "search_term": "Search Term",
    "impressions": "Impressions",
    "clicks": "Clicks",
    "ctr": "CTR",
    "spend": "Spend",
    "cpc": "CPC",
    "orders": "Orders",
    "sales": "Sales",
    "acos": "ACoS",
}

GAP_COLUMNS = ["keyword", "source", "score", "in_ads", "in_organic", "opportunity"]

GAP_DISPLAY = {
    "keyword": "Keyword",
    "source": "Source",
    "score": "Score",
    "in_ads": "In Ads?",
    "in_organic": "In Organic?",
    "opportunity": "Opportunity",
}


class GapsWorker(BaseWorker):
    """Worker for computing keyword gaps."""

    def run_task(self):
        from kdp_scout.reporting import ReportingEngine

        self.status.emit("Analyzing keyword gaps...")
        engine = ReportingEngine()
        gaps = engine.keyword_gaps()

        self.log.emit(f"Found {len(gaps)} keyword gaps")
        self.status.emit(f"Found {len(gaps)} gaps")
        return gaps


class DropZone(QFrame):
    """Drag & drop zone for file import."""

    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setProperty("class", "drop-zone")
        self.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel("📂")
        icon_label.setStyleSheet("font-size: 36px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        text_label = QLabel("Drag & drop Amazon Ads CSV here\nor click Browse")
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_label.setProperty("class", "drop-zone-text")
        layout.addWidget(text_label)

        browse_btn = QPushButton("Browse...")
        browse_btn.setProperty("class", "btn-primary")
        browse_btn.setFixedWidth(120)
        browse_btn.clicked.connect(self._browse)
        layout.addWidget(browse_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith('.csv'):
                event.acceptProposedAction()
                self.setProperty("class", "drop-zone-active")
                self.style().unpolish(self)
                self.style().polish(self)

    def dragLeaveEvent(self, event):
        self.setProperty("class", "drop-zone")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("class", "drop-zone")
        self.style().unpolish(self)
        self.style().polish(self)

        urls = event.mimeData().urls()
        if urls:
            filepath = urls[0].toLocalFile()
            if filepath.lower().endswith('.csv'):
                self.file_dropped.emit(filepath)

    def _browse(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open Amazon Ads CSV", "", "CSV Files (*.csv);;All Files (*)"
        )
        if filepath:
            self.file_dropped.emit(filepath)


class AdsPage(QWidget):
    """Page for Amazon Ads data import and analysis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._imported_data = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("<h2>📊 Ads Analysis</h2>")
        layout.addWidget(header)

        # Drop zone
        self._drop_zone = DropZone()
        self._drop_zone.file_dropped.connect(self._on_file_imported)
        layout.addWidget(self._drop_zone)

        # Status
        self._import_status = QLabel("")
        self._import_status.setProperty("class", "info-text")
        layout.addWidget(self._import_status)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.setProperty("class", "main-tabs")

        # Search Terms tab
        self._search_terms_table = DataTable()
        self._tabs.addTab(self._search_terms_table, "🔍 Search Terms Performance")

        # Gaps tab
        gaps_widget = QWidget()
        gaps_layout = QVBoxLayout(gaps_widget)
        gaps_layout.setContentsMargins(0, 8, 0, 0)

        gaps_toolbar = QHBoxLayout()
        self._gaps_refresh_btn = QPushButton("🔄 Analyze Gaps")
        self._gaps_refresh_btn.setProperty("class", "btn-primary")
        self._gaps_refresh_btn.clicked.connect(self._on_analyze_gaps)
        gaps_toolbar.addWidget(self._gaps_refresh_btn)
        gaps_toolbar.addStretch()
        gaps_layout.addLayout(gaps_toolbar)

        self._gaps_table = DataTable()
        gaps_layout.addWidget(self._gaps_table, 1)

        self._tabs.addTab(gaps_widget, "🔎 Keyword Gaps")

        layout.addWidget(self._tabs, 1)

        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

    def _on_file_imported(self, filepath: str):
        try:
            self._progress.start()
            self._progress.set_status(f"Importing {os.path.basename(filepath)}...")

            data = self._parse_ads_csv(filepath)

            if not data:
                self._progress.finish("No data found in CSV")
                QMessageBox.warning(self, "Import", "No data found in the CSV file.")
                return

            self._imported_data = data
            self._import_status.setText(
                f"✅ Imported {len(data)} search terms from {os.path.basename(filepath)}"
            )

            # Aggregate by search term
            aggregated = self._aggregate_search_terms(data)
            self._search_terms_table.load_data(
                aggregated, SEARCH_TERM_COLUMNS, SEARCH_TERM_DISPLAY
            )

            # Also store in DB
            try:
                from kdp_scout.db import AdsRepository
                repo = AdsRepository()
                repo.import_search_terms(data)
                repo.close()
                self._progress.append_log(f"Stored {len(data)} records in database")
            except Exception as e:
                self._progress.append_log(f"Warning: Could not store in DB: {e}")

            self._progress.finish(f"Imported {len(data)} search terms")

            try:
                SearchHistory.instance().log(
                    tool="Ads", action="Import CSV",
                    query=os.path.basename(filepath),
                    results=aggregated, result_count=len(data),
                )
            except Exception:
                pass

        except Exception as e:
            self._progress.finish(f"Import error: {e}")
            QMessageBox.critical(self, "Import Error", str(e))

    def _parse_ads_csv(self, filepath: str) -> List[Dict[str, Any]]:
        rows = []

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            # Skip potential header rows (Amazon reports sometimes have metadata rows)
            lines = f.readlines()

        # Find the header row (first row with recognizable column names)
        header_idx = 0
        for i, line in enumerate(lines):
            lower = line.lower()
            if any(term in lower for term in ['search term', 'customer search term',
                                                'impressions', 'keyword']):
                header_idx = i
                break

        # Parse from header row
        content = ''.join(lines[header_idx:])
        reader = csv.DictReader(content.splitlines())

        for raw_row in reader:
            row = {}
            for csv_col, value in raw_row.items():
                if csv_col is None:
                    continue
                mapped = AMAZON_ADS_COLUMN_MAP.get(csv_col.strip(), csv_col.strip().lower().replace(' ', '_'))
                # Clean numeric values
                if isinstance(value, str):
                    value = value.strip()
                    if value.startswith('$'):
                        value = value.replace('$', '').replace(',', '')
                    if value.endswith('%'):
                        value = value.replace('%', '')
                    try:
                        if '.' in value:
                            value = float(value)
                        elif value.isdigit():
                            value = int(value)
                    except (ValueError, AttributeError):
                        pass
                row[mapped] = value

            if row.get('search_term') or row.get('keyword'):
                if 'search_term' not in row and 'keyword' in row:
                    row['search_term'] = row['keyword']
                rows.append(row)

        return rows

    def _aggregate_search_terms(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        agg = {}
        for row in data:
            term = row.get('search_term', '')
            if not term:
                continue

            if term not in agg:
                agg[term] = {
                    'search_term': term,
                    'impressions': 0,
                    'clicks': 0,
                    'spend': 0.0,
                    'orders': 0,
                    'sales': 0.0,
                }

            entry = agg[term]
            entry['impressions'] += int(row.get('impressions', 0) or 0)
            entry['clicks'] += int(row.get('clicks', 0) or 0)
            entry['spend'] += float(row.get('spend', 0) or 0)
            entry['orders'] += int(row.get('orders', 0) or 0)
            entry['sales'] += float(row.get('sales', 0) or 0)

        # Calculate derived metrics
        result = []
        for entry in agg.values():
            impressions = entry['impressions']
            clicks = entry['clicks']
            spend = entry['spend']
            orders = entry['orders']
            sales = entry['sales']

            entry['ctr'] = f"{(clicks / impressions * 100):.2f}%" if impressions > 0 else "0.00%"
            entry['cpc'] = round(spend / clicks, 2) if clicks > 0 else 0.0
            entry['acos'] = f"{(spend / sales * 100):.1f}%" if sales > 0 else "N/A"
            entry['spend'] = round(spend, 2)
            entry['sales'] = round(sales, 2)

            result.append(entry)

        # Sort by impressions descending
        result.sort(key=lambda x: x.get('impressions', 0), reverse=True)
        return result

    def _on_analyze_gaps(self):
        self._gaps_refresh_btn.setEnabled(False)
        self._progress.start()

        self._worker = GapsWorker()
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_gaps_finished)
        self._worker.error.connect(self._on_gaps_error)
        self._worker.start()

    def _on_gaps_finished(self, result):
        self._gaps_refresh_btn.setEnabled(True)
        count = len(result) if result else 0
        try:
            SearchHistory.instance().log(
                tool="Ads", action="Gap Analysis",
                results=result, result_count=count,
            )
        except Exception:
            pass
        self._progress.finish(f"Found {count} keyword gaps")

        if result:
            self._gaps_table.load_data(result, GAP_COLUMNS, GAP_DISPLAY)
        self._worker = None

    def _on_gaps_error(self, error_msg: str):
        self._gaps_refresh_btn.setEnabled(True)
        self._progress.finish(f"Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def focus_search(self):
        self._search_terms_table.focus_search()
