from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QFormLayout, QLineEdit, QMessageBox, QFrame,
)
from PyQt6.QtCore import Qt

from scout.gui.widgets.progress_panel import ProgressPanel
from scout.gui.workers.pod_workers import PodProductLookupAmazonWorker
from scout.gui.search_history import SearchHistory


class PodProductLookupPage(QWidget):
    """Look up an Amazon Merch product by ASIN or amazon.com URL."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._product_data = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("<h2>🔎 Amazon Merch Product Lookup</h2>")
        header.setStyleSheet("color: #cba6f7;")
        layout.addWidget(header)

        desc = QLabel(
            "Enter an Amazon Merch ASIN (e.g. B09XYZ1234) or a full amazon.com product URL "
            "to extract the title, bullet keywords, and price."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(desc)

        input_group = QGroupBox("Product Input")
        input_layout = QFormLayout(input_group)

        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("ASIN (B09XYZ1234) or https://www.amazon.com/dp/B09XYZ1234")
        self._url_input.returnPressed.connect(self._start_lookup)
        input_layout.addRow("ASIN / URL:", self._url_input)

        layout.addWidget(input_group)

        btn_layout = QHBoxLayout()

        self._lookup_btn = QPushButton("🔎  Lookup Product")
        self._lookup_btn.setProperty("class", "btn-primary")
        self._lookup_btn.clicked.connect(self._start_lookup)
        btn_layout.addWidget(self._lookup_btn)

        btn_layout.addStretch()

        self._analyze_btn = QPushButton("🔬  Analyze Niche")
        self._analyze_btn.setEnabled(False)
        self._analyze_btn.clicked.connect(self._analyze_niche)
        btn_layout.addWidget(self._analyze_btn)

        layout.addLayout(btn_layout)

        # Results panel
        self._results_frame = QFrame()
        self._results_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._results_frame.setStyleSheet("background: #1e1e2e; border-radius: 6px; padding: 4px;")
        results_layout = QVBoxLayout(self._results_frame)

        self._results_label = QLabel("Enter an ASIN or Amazon URL above to get started.")
        self._results_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._results_label.setWordWrap(True)
        self._results_label.setStyleSheet("color: #6c7086; font-size: 13px; padding: 32px;")
        self._results_label.setTextFormat(Qt.TextFormat.RichText)
        results_layout.addWidget(self._results_label)

        layout.addWidget(self._results_frame, 1)

        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._cancel_worker)
        layout.addWidget(self._progress)

    def _start_lookup(self):
        raw = self._url_input.text().strip()
        if not raw:
            QMessageBox.warning(self, "Input required", "Please enter an ASIN or Amazon URL.")
            return

        self._progress.start()
        self._lookup_btn.setEnabled(False)
        self._analyze_btn.setEnabled(False)
        self._results_label.setText("Looking up product...")
        self._results_label.setStyleSheet("color: #a6adc8; font-size: 13px; padding: 32px;")

        self._worker = PodProductLookupAmazonWorker(raw)
        self._worker.status.connect(self._progress.set_status)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.log.connect(self._progress.set_status)
        self._worker.finished_with_result.connect(self._on_lookup_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_lookup_finished(self, product_data):
        self._progress.finish("✅  Lookup complete")
        self._lookup_btn.setEnabled(True)
        self._product_data = product_data

        if not product_data.get("title"):
            self._results_label.setText(
                "<span style='color:#f38ba8;'>❌  Product not found. "
                "Check the ASIN or URL and try again.</span>"
            )
            return

        title    = product_data.get("title", "N/A")
        asin     = product_data.get("asin", "—")
        price    = product_data.get("price", 0) or 0
        keywords = product_data.get("keywords", [])
        kw_html  = "".join(f"<li>{k}</li>" for k in keywords) if keywords else "<li>—</li>"

        html = f"""
        <h3 style='color:#cba6f7; margin-bottom:8px;'>✅ Product Found</h3>
        <table cellspacing='6' style='font-size:13px;'>
          <tr><td style='color:#6c7086; width:110px;'>ASIN</td>
              <td style='color:#cdd6f4;'><b>{asin}</b></td></tr>
          <tr><td style='color:#6c7086;'>Title</td>
              <td style='color:#cdd6f4;'>{title}</td></tr>
          <tr><td style='color:#6c7086;'>Price</td>
              <td style='color:#a6e3a1;'>${price:.2f}</td></tr>
        </table>
        <br>
        <span style='color:#6c7086; font-size:11px;'>EXTRACTED KEYWORDS</span>
        <ul style='color:#cdd6f4; margin-top:4px; font-size:12px;'>{kw_html}</ul>
        """
        self._results_label.setText(html)
        self._results_label.setStyleSheet("color: #cdd6f4; font-size: 13px; padding: 12px;")
        self._analyze_btn.setEnabled(True)
        self._worker = None
        try:
            SearchHistory.instance().log(
                tool="POD Product Lookup", action="lookup",
                query=product_data.get("asin", raw),
                results=product_data, result_count=1 if product_data.get("title") else 0,
            )
        except Exception:
            pass

    def _analyze_niche(self):
        if not self._product_data:
            return
        keywords = self._product_data.get("keywords", [])
        title    = self._product_data.get("title", "")
        niche    = " ".join(title.split()[:3]) if title else (keywords[0] if keywords else "")
        QMessageBox.information(
            self, "Analyze Niche",
            f"Will open Niche Analyzer with: \"{niche}\"\n\n"
            "(Navigation to Niche Analyzer page coming in next iteration)"
        )

    def _cancel_worker(self):
        if self._worker:
            self._worker.cancel()

    def _on_worker_error(self, error_msg):
        self._progress.finish(f"❌  Error: {error_msg}")
        self._lookup_btn.setEnabled(True)
        self._worker = None

    def set_asin(self, asin: str):
        """Called externally to pre-fill and trigger a lookup."""
        self._url_input.setText(asin)
        self._start_lookup()
