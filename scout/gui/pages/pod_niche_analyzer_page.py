from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QGroupBox, QFormLayout, QDoubleSpinBox,
    QMessageBox, QLineEdit,
)
from PyQt6.QtCore import Qt

from scout.gui.widgets.progress_panel import ProgressPanel
from scout.gui.workers.pod_workers import PodNicheAnalyzerWorker
from scout.gui.widgets.score_gauge import ScoreGauge
from scout.gui.search_history import SearchHistory


class PodNicheAnalyzerPage(QWidget):
    """Holy Grail page for analyzing a POD niche."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Header
        header = QLabel("<h2>🔬 POD Niche Analyzer</h2>")
        layout.addWidget(header)
        
        # Input section
        input_group = QGroupBox("Niche Parameters")
        input_layout = QFormLayout(input_group)
        
        self._niche_input = QLineEdit()
        self._niche_input.setPlaceholderText("Enter a niche (e.g., cat lover, nurse gift...)")
        input_layout.addRow("Niche:", self._niche_input)
        
        self._platform_combo = QComboBox()
        self._platform_combo.addItems(["All", "Merch Amazon", "Etsy", "Redbubble", "Pinterest"])
        input_layout.addRow("Platform:", self._platform_combo)
        
        layout.addWidget(input_group)
        
        # Gauges (5 gauges)
        gauges_group = QGroupBox("Niche Scores")
        gauges_layout = QHBoxLayout(gauges_group)
        
        self._demand_gauge = ScoreGauge("Demand")
        self._competition_gauge = ScoreGauge("Competition")
        self._profitability_gauge = ScoreGauge("Profitability")
        self._trend_gauge = ScoreGauge("Trend")
        self._virality_gauge = ScoreGauge("Visual Viralty")
        
        gauges_layout.addWidget(self._demand_gauge)
        gauges_layout.addWidget(self._competition_gauge)
        gauges_layout.addWidget(self._profitability_gauge)
        gauges_layout.addWidget(self._trend_gauge)
        gauges_layout.addWidget(self._virality_gauge)
        
        layout.addWidget(gauges_group)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        self._analyze_btn = QPushButton("🔬 Analyze Niche")
        self._analyze_btn.setProperty("class", "btn-primary")
        self._analyze_btn.clicked.connect(self._start_analysis)
        btn_layout.addWidget(self._analyze_btn)
        
        btn_layout.addStretch()
        
        self._export_btn = QPushButton("📤 Export Report")
        self._export_btn.clicked.connect(self._export_report)
        btn_layout.addWidget(self._export_btn)
        
        layout.addLayout(btn_layout)
        
        # Progress
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._cancel_worker)
        layout.addWidget(self._progress)
        
        # Results placeholder
        self._results_label = QLabel("Enter a niche and click 'Analyze' to start.")
        self._results_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._results_label.setStyleSheet("color: #6c7086; font-size: 14px; padding: 40px;")
        layout.addWidget(self._results_label, 1)
    
    def _start_analysis(self):
        niche = self._niche_input.text().strip()
        if not niche:
            QMessageBox.warning(self, "Input Required", "Please enter a niche to analyze.")
            return
        
        platform = self._platform_combo.currentText().lower()
        if platform == "all":
            platform = "all"
        else:
            platform = platform.lower().replace(" ", "_")
        
        self._progress.start()
        self._analyze_btn.setEnabled(False)
        self._results_label.hide()
        
        self._worker = PodNicheAnalyzerWorker(niche, platform)
        self._worker.status.connect(self._progress.set_status)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.log.connect(self._progress.set_status)
        self._worker.finished_with_result.connect(self._on_analysis_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()
    
    def _on_analysis_finished(self, result):
        self._progress.finish("Analysis complete!")
        self._analyze_btn.setEnabled(True)
        
        # Update gauges
        self._demand_gauge.set_score(result.get("demand_score", 0.0))
        self._competition_gauge.set_score(result.get("competition_score", 0.0))
        self._profitability_gauge.set_score(result.get("profitability_score", 0.0))
        self._trend_gauge.set_score(result.get("trend_score", 0.0))
        self._virality_gauge.set_score(result.get("visual_virality", 0.0))
        
        # Show results
        self._results_label.setText(
            f"<h3>Analysis for: {result.get('niche', '')}</h3>"
            f"<p><b>Global Score:</b> {result.get('global_score', 0):.2f}</p>"
            f"<p><b>Recommended Platform:</b> {result.get('recommended_platform', 'N/A')}</p>"
        )
        self._results_label.show()
        
        self._worker = None
        try:
            SearchHistory.instance().log(
                tool="POD Niche Analyzer", action="analyze",
                query=result.get("niche", ""),
                results=result, result_count=1,
                notes=f"Global: {result.get('global_score', 0):.1f} | {result.get('recommended_platform', '')}",
            )
        except Exception:
            pass
    
    def _export_report(self):
        QMessageBox.information(self, "Export", "Report export will be available soon!")
    
    def _cancel_worker(self):
        if self._worker:
            self._worker.cancel()
    
    def _on_worker_error(self, error_msg):
        self._progress.finish(f"Error: {error_msg}")
        self._analyze_btn.setEnabled(True)
        self._worker = None
